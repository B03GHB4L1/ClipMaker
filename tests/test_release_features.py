"""Release feature acceptance, independent of the release/package pipeline.

Baseline reviewed: older versions/{Windows,Linux,Mac}/clipmaker_core.py, all
SHA256 11b6ade0fba4cdeef086bb09a4be9de1918dc93db14f9792a7537bb76facafc0,
and the historical filtering page's PASS_TYPE_MAP and qualifier-logic help.
The explicit manifest below is the parity checklist for all 64 non-AI flags.
It deliberately does not derive expected semantics from the implementation.

Historical behavior combined ANY/ALL within identical action scopes. Intended
release behavior extends ALL across every rule applicable to an event, including
overlapping scopes. Unselected families are excluded unless explicitly selected;
outcome, context, progression and the newer unscoped flags remain AND constraints.
Tests named ``must`` protect corrections to historical bugs: overlapping ALL
scopes and preserving the original shootout anchor through team/player filters.
Synthetic media checks prove engine source/time selection, not native UI,
real-provider qualifier extraction, or packaged application acceptance.
"""

from pathlib import Path
import queue
import re
import subprocess
import tempfile
import unittest

import pandas as pd

from packaging.clipmaker_api_server import (
    FILTER_QUALIFIERS,
    MatchStore,
    build_clip_config,
    compute_clip_windows,
    load_filter_options,
    render_preview_clip,
    video_for_period,
)
from app.project_analysis import project_session
import clipmaker_core as core


SHOTS = frozenset({
    "SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost",
    "BlockedShot", "AttemptSaved", "Attempt",
})
SCOPES = {
    "pass": frozenset({"Pass"}), "shot": SHOTS,
    "goal": frozenset({"Goal"}), "save": frozenset({"Save"}),
    "card": frozenset({"Card"}), "takeon": frozenset({"TakeOn"}),
    "carry": frozenset({"Carry"}), "global": None,
}

# Explicit baseline checklist: flag, backing column, historical scope.
# "global" is intentional even when the shared catalog groups a flag as Shots.
CHECKLIST = tuple(tuple(line.split()) for line in """
successful_only outcomeType outcome_success
unsuccessful_only outcomeType outcome_failure
progressive_only __progressive__ progressive
fast_break_only is_fast_break global
touch_in_box_only is_touch_in_box global
key_passes_only is_key_pass pass
crosses_only is_cross pass
long_balls_only is_long_ball pass
switches_only is_switch_of_play pass
diagonals_only is_diagonal_long_ball pass
through_balls_only is_through_ball pass
corners_only is_corner pass
freekicks_only is_freekick pass
headers_only is_header pass
throw_ins_only is_throw_in pass
goal_kicks_only is_goal_kick pass
keeper_throws_only is_keeper_throw pass
gk_hoofs_only is_gk_hoof pass
pull_backs_only is_pull_back pass
lay_offs_only is_lay_off pass
flick_ons_only is_flick_on pass
launches_only is_launch pass
assists_only is_assist pass
attacking_passes_only is_attacking_pass pass
box_entry_pass_only is_box_entry_pass pass
deep_completion_only is_deep_completion pass
final_third_entry_pass_only is_final_third_entry_pass pass
big_chances_only is_big_chance_shot shot
own_goals_only is_own_goal goal
penalties_only is_penalty shot
volleys_only is_volley shot
chipped_only is_chipped shot
direct_from_corner_only is_direct_from_corner shot
left_foot_only is_left_foot shot
right_foot_only is_right_foot shot
scrambles_only is_scramble global
corner_situations_only is_corner_situation global
shot_strong_only is_shot_strong global
shot_weak_only is_shot_weak global
individual_play_only is_individual_play global
follows_dribble_only is_follows_dribble global
one_on_one_only is_1on1 global
deflected_only is_deflected global
woodwork_only is_hit_woodwork global
back_heel_only is_back_heel global
big_chances_created_only is_big_chance pass
assist_throughball_only is_assist_throughball pass
assist_cross_only is_assist_cross pass
assist_corner_only is_assist_corner pass
assist_freekick_only is_assist_freekick pass
intentional_assists_only is_intentional_assist pass
gk_saves_only is_gk_save save
yellow_cards_only is_yellow_card card
red_cards_only is_red_card card
second_yellow_only is_second_yellow card
nutmegs_only is_nutmeg takeon
success_in_box_only is_success_in_box takeon
box_entry_carry_only is_box_entry_carry carry
final_third_entry_carry_only is_final_third_entry_carry carry
last_line_only is_last_line global
forced_out_only is_forced_out global
blocked_cross_only is_blocked_cross global
errors_to_shot_only is_error_led_to_shot global
errors_to_goal_only is_error_led_to_goal global
""".strip().splitlines())
BOOLEAN_COLUMNS = {column for _, column, _ in CHECKLIST if column.startswith("is_")}


def event(identifier, event_type="Pass", **changes):
    row = dict.fromkeys(BOOLEAN_COLUMNS, False)
    row.update(id=identifier, type=event_type, minute=1, second=0, period=1,
               team="Home", playerName="One", outcomeType="Successful",
               prog_pass=0, prog_carry=0, xT=0, pitch_zone="Centre",
               depth_zone="Middle Third")
    row.update(changes)
    return row


class FilterAcceptance(unittest.TestCase):
    def assert_selection(self, rows, config, expected):
        frame = pd.DataFrame(rows, index=[10 + 3 * i for i in range(len(rows))])
        result, removed = core.apply_filters(frame, config)
        self.assertEqual(result["id"].tolist(), expected)
        self.assertEqual(removed, len(rows) - len(expected))
        self.assertNotIn("_xt_num", result.columns)

    def test_catalog_matches_all_64_explicit_non_ai_semantics(self):
        self.assertEqual(len(CHECKLIST), 64)
        self.assertEqual(len({flag for flag, _, _ in CHECKLIST}), 64)
        self.assertEqual(len(FILTER_QUALIFIERS), 64)
        self.assertEqual({flag: column for flag, column, _ in CHECKLIST},
                         {flag: column for flag, column, *_ in FILTER_QUALIFIERS})

    def test_every_flag_survives_config_and_data_aware_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "events.csv"
            match = {"id": "release-filters", "csv_path": str(path),
                     "markers": {"1H": "00:00:00", "2H": "00:00:00"}}
            for flag, column, kind in CHECKLIST:
                with self.subTest(flag=flag):
                    row = event("match")
                    if kind == "outcome_failure":
                        row[column] = "Unsuccessful"
                    elif kind == "progressive":
                        row["prog_carry"] = "1"
                    elif column.startswith("is_"):
                        row[column] = " yes "
                    pd.DataFrame([row]).to_csv(path, index=False)
                    available = {item["flag"]: item for item in load_filter_options(match)["qualifiers"]}
                    self.assertTrue(available[flag]["available"])
                    self.assertEqual(available[flag]["count"], 1)
                    for logic in ("any", "all"):
                        config = build_clip_config(match, {flag: True, "qualifier_logic": logic}, root)
                        self.assertTrue(config[flag])
                        self.assertEqual(config["qualifier_logic"], logic)
                        self.assertEqual({key for key, _, _ in CHECKLIST if config[key]}, {flag})
            pd.DataFrame([{"minute": 1, "second": 0, "period": 1, "type": "Pass"}]).to_csv(path, index=False)
            self.assertTrue(all(not item["available"] and item["count"] == 0
                                for item in load_filter_options(match)["qualifiers"]))
            with self.assertRaisesRegex(ValueError, "Qualifier logic"):
                build_clip_config(match, {"qualifier_logic": "xor"}, root)

    def test_progressive_numeric_boundaries_and_mixed_families(self):
        rows = [event("pass", prog_pass="0.1"), event("carry", "Carry", prog_carry=2),
                event("zero", prog_pass=0), event("negative", "Carry", prog_carry=-1),
                event("missing", prog_pass=None), event("invalid", prog_carry="bad"),
                event("shot", "Goal")]
        for logic in ("any", "all"):
            for types, expected in (([], ["pass", "carry"]),
                                    (["Pass", "Carry", "Goal"], ["pass", "carry", "shot"])):
                with self.subTest(logic=logic, types=types):
                    self.assert_selection(rows, {"progressive_only": True,
                        "qualifier_logic": logic, "filter_types": types}, expected)

    def test_legacy_computed_qualifiers_are_backfilled_from_geometry(self):
        # These rows omit derived flags: exercise the actual old-CSV fallback,
        # including open-play exclusions and entry boundary coordinates.
        cases = (
            ("switches_only", "is_switch_of_play", [
                (True, {"x": 20, "y": 20, "endX": 50, "endY": 80, "is_long_ball": True}),
                (False, {"x": 20, "y": 20, "endX": 50, "endY": 80, "is_long_ball": False}),
                (False, {"x": 20, "y": 40, "endX": 50, "endY": 55, "is_long_ball": True})]),
            ("diagonals_only", "is_diagonal_long_ball", [
                (True, {"x": 10, "y": 20, "endX": 22, "endY": 38, "is_long_ball": True}),
                (False, {"x": 10, "y": 20, "endX": 21, "endY": 38, "is_long_ball": True}),
                (False, {"x": 10, "y": 20, "endX": 30, "endY": 37, "is_long_ball": True}),
                (False, {"x": 10, "y": 20, "endX": 30, "endY": 80, "is_long_ball": True})]),
            ("box_entry_pass_only", "is_box_entry_pass", [
                (True, {"x": 83, "y": 50, "endX": 84, "endY": 50}),
                (False, {"x": 70, "y": 50, "endX": 83, "endY": 50}),
                (False, {"x": 70, "y": 50, "endX": 90, "endY": 21}),
                (False, {"x": 70, "y": 50, "endX": 90, "endY": 79}),
                (False, {"x": 85, "y": 50, "endX": 90, "endY": 50}),
                (False, {"x": 70, "y": 50, "endX": 90, "endY": 50, "is_corner": True})]),
            ("deep_completion_only", "is_deep_completion", [
                (True, {"endX": 90, "endY": 50}),
                (False, {"endX": 80, "endY": 50}),
                (False, {"endX": 90, "endY": 50, "is_cross": True}),
                (False, {"endX": 90, "endY": 50, "is_freekick": True}),
                (False, {"endX": 90, "endY": 50, "outcomeType": "Unsuccessful"})]),
            ("box_entry_carry_only", "is_box_entry_carry", [
                (True, {"type": "Carry", "x": 83, "y": 50, "endX": 84, "endY": 50}),
                (False, {"type": "Carry", "x": 85, "y": 50, "endX": 90, "endY": 50}),
                (False, {"type": "Carry", "x": 70, "y": 50, "endX": 83, "endY": 50})]),
            ("final_third_entry_pass_only", "is_final_third_entry_pass", [
                (True, {"x": 66, "endX": 67}), (False, {"x": 67, "endX": 80}),
                (False, {"x": 66, "endX": 66.99}),
                (False, {"x": 66, "endX": 80, "is_freekick": True})]),
            ("final_third_entry_carry_only", "is_final_third_entry_carry", [
                (True, {"type": "Carry", "x": 66, "endX": 67}),
                (False, {"type": "Carry", "x": 67, "endX": 80}),
                (False, {"type": "Carry", "x": 66, "endX": 66.99})]),
        )
        for flag, column, samples in cases:
            rows = [event(str(i), **values) for i, (_, values) in enumerate(samples)]
            for row in rows:
                del row[column]
            expected = [str(i) for i, (matches, _) in enumerate(samples) if matches]
            for logic in ("any", "all"):
                with self.subTest(flag=flag, logic=logic):
                    self.assert_selection(rows, {flag: True, "qualifier_logic": logic}, expected)

    def test_missing_legacy_columns_keep_historical_warning_or_false_default(self):
        rows = [{"id": "legacy", "type": "Pass", "minute": 1, "period": 1}]
        for logic in ("any", "all"):
            for flag, expected, warning in (("crosses_only", ["legacy"], True),
                                             ("throw_ins_only", [], False),
                                             ("progressive_only", ["legacy"], False)):
                with self.subTest(flag=flag, logic=logic):
                    messages = []
                    result, removed = core.apply_filters(pd.DataFrame(rows),
                        {flag: True, "qualifier_logic": logic}, log=messages.append)
                    self.assertEqual(result["id"].tolist(), expected)
                    self.assertEqual(removed, 1 - len(expected))
                    self.assertEqual(any("filter skipped" in message for message in messages), warning)

    def test_outcomes_remain_constraints_even_with_any(self):
        rows = [event("successful", is_cross=True),
                event("unsuccessful", is_cross=True, outcomeType="Unsuccessful"),
                event("unknown", is_cross=True, outcomeType=None),
                event("wrong-case", is_cross=True, outcomeType="successful")]
        for logic in ("any", "all"):
            for flag, expected in (("successful_only", ["successful"]),
                                   ("unsuccessful_only", ["unsuccessful"])):
                with self.subTest(logic=logic, flag=flag):
                    self.assert_selection(rows, {flag: True, "crosses_only": True,
                        "qualifier_logic": logic}, expected)
            self.assert_selection(rows, {"successful_only": True,
                "unsuccessful_only": True, "qualifier_logic": logic}, [])

    def test_cross_family_any_all_preserves_explicit_unqualified_actions(self):
        rows = [event("cross", is_cross=True), event("plain-pass"),
                event("penalty", "Goal", is_penalty=True), event("plain-shot", "SavedShot"),
                event("nutmeg", "TakeOn", is_nutmeg=True), event("plain-dribble", "TakeOn"),
                event("tackle", "Tackle")]
        for logic in ("any", "all"):
            options = {"crosses_only": True, "penalties_only": True,
                       "nutmegs_only": True, "qualifier_logic": logic}
            with self.subTest(logic=logic, explicit_types=False):
                self.assert_selection(rows, options, ["cross", "penalty", "nutmeg"])
            with self.subTest(logic=logic, explicit_types=True):
                self.assert_selection(rows, {**options, "filter_types": [
                    "Pass", "Goal", "SavedShot", "TakeOn", "Tackle"]},
                    ["cross", "penalty", "nutmeg", "tackle"])

    def test_corners_and_freekicks_follow_selected_any_all(self):
        rows = [event("corner", is_corner=True), event("freekick", is_freekick=True),
                event("both", is_corner=True, is_freekick=True), event("neither")]
        for logic, expected in (("any", ["corner", "freekick", "both"]), ("all", ["both"])):
            with self.subTest(logic=logic):
                self.assert_selection(rows, {"corners_only": True, "freekicks_only": True,
                                            "qualifier_logic": logic}, expected)

    def test_attacking_chaos_is_shots_or_key_passes(self):
        rows = [event("key", is_key_pass=True), event("plain"),
                event("dribble", "TakeOn", is_key_pass=True)]
        rows += [event(kind, kind) for kind in sorted(SHOTS)]
        for logic in ("any", "all"):
            with self.subTest(logic=logic):
                self.assert_selection(rows, {"shots_and_key_passes_only": True,
                    "key_passes_only": True, "qualifier_logic": logic}, ["key", *sorted(SHOTS)])

    def test_all_overlapping_shot_scopes_must_intersect(self):
        rows = [event("own-only", "Goal", is_own_goal=True),
                event("right-foot-only", "Goal", is_right_foot=True),
                event("both", "Goal", is_own_goal=True, is_right_foot=True),
                event("saved-right-foot", "SavedShot", is_right_foot=True)]
        self.assert_selection(rows, {"own_goals_only": True, "right_foot_only": True,
            "filter_types": ["Goal"], "qualifier_logic": "all"}, ["both"])

    def test_xt_progression_time_zones_and_top_n_mixed_reel(self):
        rows = [event("cross", is_cross=True, prog_pass=1, xT="0.4", minute=10),
                event("key", is_key_pass=True, prog_pass=1, xT="0.6", minute=20),
                event("both", is_cross=True, is_key_pass=True, prog_pass=1, xT="0.5", minute=30),
                event("not-progressive", is_cross=True, xT="9", minute=30),
                event("low-xt", is_cross=True, prog_pass=1, xT="bad", minute=30),
                event("early", is_cross=True, prog_pass=1, xT=8, minute=9),
                event("late", is_cross=True, prog_pass=1, xT=8, minute=31),
                event("shot", "Goal", minute=30, xT=0),
                event("wrong-zone", "Goal", minute=20, pitch_zone="Right Wing"),
                event("wrong-depth", "Goal", minute=20, depth_zone="Defensive Third")]
        options = {"filter_types": ["Pass", "Goal"], "crosses_only": True,
                   "key_passes_only": True, "progressive_only": True, "xt_min": .2,
                   "top_n": 1, "minute_min": 10, "minute_max": 30,
                   "pitch_zone_filter": "Centre", "depth_zone_filter": "Middle Third"}
        for logic, expected in (("any", ["key", "shot"]), ("all", ["both", "shot"])):
            with self.subTest(logic=logic):
                self.assert_selection(rows, {**options, "qualifier_logic": logic}, expected)

    def test_team_players_period_and_qualifiers_reach_preview(self):
        rows = [event("cross", is_cross=True, minute=1),
                event("key", is_key_pass=True, playerName="Two", minute=2),
                event("other-player", is_cross=True, playerName="Three", minute=3),
                event("other-team", is_cross=True, team="Away", minute=4),
                event("second-half", is_cross=True, period=2, minute=46)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "events.csv"
            pd.DataFrame(rows).to_csv(path, index=False)
            original = path.read_bytes()
            match = {"id": "mixed", "csv_path": str(path),
                     "markers": {"1H": "00:00:00", "2H": "00:00:00"}}
            config = build_clip_config(match, {"team_filter": "Home", "player_filters": ["One", "Two"],
                "half_filter": "1st half only", "filter_types": ["Pass"],
                "crosses_only": True, "key_passes_only": True, "qualifier_logic": "any",
                "before_buffer": 1, "after_buffer": 1, "min_gap": 0}, root)
            windows = compute_clip_windows(config)
            self.assertEqual([(w["period"], w["start"], w["end"]) for w in windows],
                             [(1, 59, 61), (1, 119, 121)])
            self.assertIn("One - Pass", windows[0]["label"])
            self.assertIn("Two - Pass", windows[1]["label"])
            self.assertNotEqual(config["data_file"], str(path))
            self.assertEqual(path.read_bytes(), original)


def qualifier_case(flag, column, kind):
    """Give every manifest entry a separately discoverable acceptance result."""
    def test(self):
        for logic in ("any", "all"):
            with self.subTest(logic=logic):
                options = {flag: True, "qualifier_logic": logic}
                if kind.startswith("outcome_"):
                    expected = "Successful" if kind == "outcome_success" else "Unsuccessful"
                    rows = [event("yes", outcomeType=expected),
                            event("no", outcomeType="Unsuccessful" if expected == "Successful" else "Successful"),
                            event("null", outcomeType=None)]
                    self.assert_selection(rows, options, ["yes"])
                elif kind == "progressive":
                    rows = [event("pass", prog_pass=1), event("carry", "Carry", prog_carry="2"), event("no")]
                    self.assert_selection(rows, options, ["pass", "carry"])
                    for row in rows:
                        row["is_cross"] = row["id"] == "pass"
                    self.assert_selection(rows, {**options, "crosses_only": True}, ["pass"])
                else:
                    scope = SCOPES[kind]
                    event_types = sorted(scope) if scope else ["Pass", "Goal", "Tackle"]
                    rows, expected = [], []
                    for event_type in event_types:
                        # Exercise persisted CSV spellings, nulls and malformed values.
                        for index, value in enumerate((True, "TRUE", " 1 ", "yes", False, "FALSE", "0", "no", None, "bad")):
                            identifier = f"{event_type}-{index}"
                            rows.append(event(identifier, event_type, **{column: value}))
                            if index < 4:
                                expected.append(identifier)
                    self.assert_selection(rows, options, expected)
                    if scope:
                        # A true bit on an unrelated action cannot satisfy a scoped qualifier.
                        rows = [event("yes", event_types[0], **{column: True}),
                                event("no", event_types[0]), event("unrelated", "Tackle", **{column: True})]
                        self.assert_selection(rows, options, ["yes"])
                        self.assert_selection(rows, {**options, "filter_types": [*event_types, "Tackle"]},
                                              ["yes", "unrelated"])
                        peer = next(((f, c) for f, c, k in CHECKLIST if k == kind and f != flag), None)
                        if peer:
                            peer_flag, peer_column = peer
                            rows = [event("first", event_types[0], **{column: True}),
                                    event("second", event_types[0], **{peer_column: True}),
                                    event("both", event_types[0], **{column: True, peer_column: True}),
                                    event("neither", event_types[0])]
                            self.assert_selection(rows, {**options, peer_flag: True},
                                ["first", "second", "both"] if logic == "any" else ["both"])
                        else:
                            rows = [event("yes", event_types[0], **{column: True}),
                                    event("unsuccessful", event_types[0], outcomeType="Unsuccessful", **{column: True})]
                            self.assert_selection(rows, {**options, "successful_only": True}, ["yes"])
                    else:
                        # Historical global flags remain AND constraints under either mode.
                        peer_flag, peer_column = ("touch_in_box_only", "is_touch_in_box") if flag == "fast_break_only" else ("fast_break_only", "is_fast_break")
                        rows = [event("first", **{column: True}), event("second", **{peer_column: True}),
                                event("both", **{column: True, peer_column: True}), event("neither")]
                        self.assert_selection(rows, {**options, peer_flag: True}, ["both"])
                        rows = [event("cross", is_cross=True, **{column: True}),
                                event("plain", **{column: True}), event("wrong-context", is_cross=True)]
                        self.assert_selection(rows, {**options, "crosses_only": True}, ["cross"])
    test.__doc__ = f"[parity] {flag}: {column}, {kind}; ANY/ALL, positives, negatives and composition."
    return test


for _flag, _column, _kind in CHECKLIST:
    setattr(FilterAcceptance, f"test_qualifier_{_flag}", qualifier_case(_flag, _column, _kind))


class SplitPeriodAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "events.csv"
        pd.DataFrame([
            event("et1", "Goal", period=3, minute=90, second=4),
            event("et2", "Goal", period=4, minute=105, second=4),
            event("start", "Start", period=5, minute=120),
            event("first-penalty", "PenaltyMissed", period=5, minute=121, second=10),
            event("second-penalty", "PenaltyScored", period=5, minute=121, second=13,
                  team="Away", playerName="Two"),
        ]).to_csv(self.csv, index=False)
        self.project = {"id": "split-periods", "csv_path": str(self.csv),
            "video_path": str(self.root / "regular.mp4"),
            "period_videos": {key: str(self.root / f"{key}.mp4") for key in ("2H", "ET1", "ET2", "PEN")},
            "markers": {"1H": "00:00:00", "2H": "00:00:00", "ET1": "00:00:01",
                        "ET2": "00:00:02", "PEN": "00:00:03"}}
        self.options = {"filter_types": ["Goal", "PenaltyMissed", "PenaltyScored"],
                        "before_buffer": 1, "after_buffer": 1, "min_gap": 0}

    def test_independent_et2_pen_sources_and_markers_survive_reopen(self):
        store = MatchStore(self.root)
        saved = store.upsert({**self.project, "filter_settings": self.options})
        reopened = MatchStore(self.root).get(saved["id"])
        self.assertEqual(reopened["markers"], self.project["markers"])
        self.assertEqual(reopened["period_videos"], self.project["period_videos"])
        config = build_clip_config(reopened, reopened["filter_settings"], self.root)
        state = project_session(reopened)
        self.assertTrue(config["split_video"])
        self.assertEqual(state["extra_time_video_mode"], "split")
        for period, key in ((3, "ET1"), (4, "ET2"), (5, "PEN")):
            with self.subTest(period=period):
                expected = reopened["period_videos"][key]
                self.assertEqual(video_for_period(reopened, period), expected)
                self.assertEqual(config[f"video{period}_file"], expected)
                self.assertEqual(state[f"video{period}_path"], expected)
                self.assertEqual(config[f"half{period}_time"], reopened["markers"][key])
                self.assertEqual(state[f"half{period}_time"], reopened["markers"][key])
        windows = compute_clip_windows(config)
        self.assertEqual([(w["period"], w["start"], w["end"]) for w in windows],
                         [(3, 4, 6), (4, 5, 7), (5, 2, 4), (5, 5, 7)])

    def test_et2_and_pen_corrections_use_match_clock_and_stay_in_period(self):
        config = build_clip_config(self.project, {**self.options, "timeline_corrections": [
            {"period": 4, "clock": "105:04", "seconds": -2},
            {"period": 5, "clock": "121:13", "seconds": 1}]}, self.root)
        windows = compute_clip_windows(config)
        self.assertEqual([(w["period"], w["start"], w["end"]) for w in windows],
                         [(3, 4, 6), (4, 3, 5), (5, 2, 4), (5, 6, 8)])

    def test_action_filter_must_not_move_first_penalty_anchor(self):
        config = build_clip_config(self.project, {**self.options, "filter_types": ["PenaltyScored"]}, self.root)
        windows = compute_clip_windows(config)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(5, 7)])

    def test_team_filter_must_not_move_first_penalty_anchor(self):
        config = build_clip_config(self.project, {**self.options, "team_filter": "Away"}, self.root)
        windows = compute_clip_windows(config)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(5, 7)])

    def test_player_filter_must_not_move_first_penalty_anchor(self):
        config = build_clip_config(self.project, {**self.options, "player_filters": ["Two"]}, self.root)
        windows = compute_clip_windows(config)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(5, 7)])

    def test_et2_and_pen_source_fallbacks_agree_with_config_and_analysis(self):
        for videos in ({"ET1": "extra.mp4"}, {"2H": "second.mp4"}, {"PEN": "penalties.mp4"}, {}):
            with self.subTest(videos=videos):
                project = {**self.project, "period_videos": videos}
                config = build_clip_config(project, self.options, self.root)
                state = project_session(project)
                for period in (3, 4, 5):
                    expected = videos.get({3: "ET1", 4: "ET2", 5: "PEN"}[period]) or (
                        videos.get("ET1") if period == 4 else None) or videos.get("2H") or project["video_path"]
                    self.assertEqual(video_for_period(project, period), expected)
                    effective_config = (config.get(f"video{period}_file") or config["video2_file"]) if config["split_video"] else config["video_file"]
                    effective_state = (state.get(f"video{period}_path") or state["video2_path"]) if state["split_video"] else state["video_path"]
                    self.assertEqual(effective_config, expected)
                    self.assertEqual(effective_state, expected)

    def test_real_preview_and_exports_use_independent_et2_pen_source_and_time(self):
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        # Wrong earlier footage is blue. Correct ET2 footage is red and PEN green
        # only after 4s. The old filtered-anchor bug seeks 2-4s instead of 5-7s,
        # so these pixels distinguish wrong timing even with the correct source.
        for path, target in ((self.project["video_path"], "blue"),
                             (self.project["period_videos"]["2H"], "blue"),
                             (self.project["period_videos"]["ET1"], "yellow"),
                             (self.project["period_videos"]["ET2"], "red"),
                             (self.project["period_videos"]["PEN"], "lime")):
            subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                f"color=c=blue:s=64x48:r=12:d=4[a];color=c={target}:s=64x48:r=12:d=5[b];[a][b]concat=n=2:v=1:a=0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
                check=True, capture_output=True, timeout=30)
        options = {**self.options, "filter_types": ["Goal", "PenaltyScored"],
                   "minute_min": 105, "dry_run": False, "encoder_preset": "ultrafast"}
        original_csv = self.csv.read_bytes()
        scenarios = (
            ("unfiltered", {}, [(4, 5, 7), (5, 5, 7)]),
            ("team", {"team_filter": "Away"}, [(5, 5, 7)]),
            ("player", {"player_filters": ["Two"]}, [(5, 5, 7)]),
            ("team-player", {"team_filter": "Away", "player_filters": ["Two"]}, [(5, 5, 7)]),
        )
        for name, filters, expected in scenarios:
            with self.subTest(filters=name):
                selected_options = {**options, **filters}
                config = build_clip_config(self.project, selected_options, self.root)
                if filters:
                    # Prove the anchor kick really was removed from the subset.
                    self.assertNotEqual(config["data_file"], str(self.csv))
                    self.assertEqual(pd.read_csv(config["data_file"])["id"].tolist(), ["second-penalty"])
                windows = compute_clip_windows(config)
                self.assertEqual([(w["period"], w["start"], w["end"]) for w in windows], expected)
                channels = [0 if period == 4 else 1 for period, _, _ in expected]
                for window, channel in zip(windows, channels):
                    preview = render_preview_clip(video_for_period(self.project, window["period"]),
                        window["start"], window["end"], self.root / "previews", 20, "ultrafast", "128k")
                    for sample in (.5, 1.5):
                        self.assert_pixel(ffmpeg, preview, sample, channel)
                for individual in (True, False):
                    with self.subTest(individual=individual):
                        config = build_clip_config(self.project, {**selected_options, "individual_clips": individual,
                            "output_dir": str(self.root / name / ("individual" if individual else "combined")),
                            "output_filename": "split.mp4"}, self.root)
                        # No edited clip_windows: the export engine must independently
                        # recover the original anchor, rather than reuse the plan.
                        self.assertEqual(config["clip_windows"], [])
                        messages, progress = queue.Queue(), queue.Queue()
                        core.run_clip_maker(config, messages, progress)
                        logs = list(messages.queue)
                        self.assertEqual([m["type"] for m in logs if m.get("type") in {"error", "done"}],
                                         ["done"], logs)
                        self.assertFalse(any(m.get("error") for m in list(progress.queue)), logs)
                        files = sorted(Path(config["output_dir"]).glob("*.mp4"))
                        self.assertEqual(len(files), len(expected) if individual else 1, logs)
                        for index, channel in enumerate(channels):
                            output = files[index] if individual else files[0]
                            for sample in (.5, 1.5):
                                self.assert_pixel(ffmpeg, output, sample + (0 if individual else index * 2), channel)
                        for output in files:
                            decoded = subprocess.run([ffmpeg, "-i", str(output), "-f", "null", "-"],
                                                     capture_output=True, text=True, timeout=30)
                            self.assertEqual(decoded.returncode, 0, decoded.stderr)
                            duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", decoded.stderr)
                            self.assertIsNotNone(duration)
                            seconds = sum(float(v) * scale for v, scale in zip(duration.groups(), (3600, 60, 1)))
                            self.assertAlmostEqual(seconds, 2 if individual else len(expected) * 2, delta=.25)
        self.assertEqual(self.csv.read_bytes(), original_csv)

    def assert_pixel(self, ffmpeg, path, seconds, channel):
        decoded = subprocess.run([ffmpeg, "-v", "error", "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            check=True, capture_output=True, timeout=30)
        self.assertEqual(len(decoded.stdout), 3)
        self.assertGreater(decoded.stdout[channel], 200, (path, decoded.stdout))
        self.assertTrue(all(value < 40 for i, value in enumerate(decoded.stdout) if i != channel),
                        (path, decoded.stdout))


if __name__ == "__main__":
    unittest.main()
