"""Focused retained-analysis acceptance; no native/browser or live provider claims.

Parity checklist reviewed against older versions/{Windows,Linux,Mac}/pages:
  [x] defensive/attacking windows, match/period isolation, positive threat sums
  [x] multi-match CSV loading, pooled style statistics, comparison scoring
  [x] tactical playlists, trace coordinates, event-window recovery
  [x] real tactical cuts/reels and comparison Top Moments reel, decoded pixels

The pages execute Streamlit navigation on import. Load their actual function
definitions and named constants with AST, without executing page startup. The
The nested comparison/cache helpers are lifted unchanged: none uses a closure.
Only the Streamlit session and temporary-file location are supplied by tests;
numerical expectations below are hand-written ledgers, not a second algorithm.
Run: python -m unittest tests.test_tactical_acceptance -v
"""

import ast
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

# MatchStore initializes the same app import path used by other repository tests.
from packaging.clipmaker_api_server import MatchStore  # noqa: F401
import clipmaker_core as core
from app.project_analysis import analysis_frame


ROOT = Path(__file__).resolve().parents[1]
TACTICAL = ROOT / "app/pages/3_Tactical_Lab.py"
COMPARISON = ROOT / "app/pages/2_The_Analysts_Room.py"


def page_functions(path):
    """Execute source functions, never Streamlit page startup or copied bodies."""
    import plotly.graph_objects as go

    namespace = dict(pd=pd, os=os, shutil=shutil, subprocess=subprocess,
                     tempfile=tempfile, analysis_frame=analysis_frame, go=go,
                     st=SimpleNamespace(session_state={}), __file__=str(path))
    for name in ("read_csv_safe", "to_seconds", "resolve_period_starts_for_video",
                 "match_clock_to_video_time", "normalise_timeline_corrections",
                 "apply_timeline_corrections"):
        namespace[name] = getattr(core, name)
    names = {"SHOT_TYPES", "DEF_WIN_TYPES", "PPDA_DEFENSIVE_ACTION_TYPES",
             "LOSS_TYPES", "IN_POSSESSION_ACTION_TYPES", "PITCH_ZONE_ORDER",
             "DEPTH_ZONE_ORDER", "PPDA_PRESS_ZONE_MIN_X", "PPDA_SCORE_CEILING",
             "PERIOD_ORDER", "PERIOD_MAP", "DEF_ACTIONS", "GK_ACTIONS",
             "_MOMENT_TIERS", "HOME_COLOR", "AWAY_COLOR", "ACCENT", "MUTED",
             "PLOTLY_EXPORT_CONFIG"}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []  # _load_csv's Streamlit cache is irrelevant.
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets):
            nodes.append(node)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"_top5_moments", "_generate_reel", "_video_identity"}:
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


def event(identifier, seconds, kind="Pass", match=0, team="Home", **changes):
    row = dict(id=identifier, minute=seconds // 60, second=seconds % 60,
               period=1, type=kind, team=team, playerName="One",
               homeTeam="Home", awayTeam="Away", outcomeType="Successful",
               match_id=match, match_label=f"Match {match}", x=20, y=50,
               endX=25, endY=50, xT=0.0, prog_pass=0, prog_carry=0,
               pitch_zone="Centre", depth_zone="Middle Third")
    for flag in ("is_box_entry_pass", "is_box_entry_carry", "is_touch_in_box",
                 "is_deep_completion", "is_final_third_entry_pass",
                 "is_final_third_entry_carry", "is_corner", "is_freekick",
                 "is_throw_in", "is_goal_kick", "is_keeper_throw", "is_gk_hoof",
                 "is_long_ball", "is_launch", "is_diagonal_long_ball", "is_key_pass"):
        row[flag] = False
    row.update(changes)
    return row


class TacticalNumericalAcceptance(unittest.TestCase):
    def setUp(self):
        self.lab = page_functions(TACTICAL)

    def frame(self, rows):
        return self.lab._prepare_df(pd.DataFrame(rows))

    def test_defensive_window_limits_and_match_period_isolation(self):
        frame = self.frame([
            event("loss", 60, "Dispossessed"),
            event("pass", 62, team="Away", xT=.2),
            event("entry", 63, team="Away", xT=-.5, is_box_entry_pass=True),
            event("shot", 68, "Goal", team="Away", xT=.3),
            event("late-recovery", 69, "BallRecovery"),
            event("other-match", 61, "Goal", match=1, team="Away", xT=9),
            event("other-period", 61, "Goal", period=2, team="Away", xT=9),
        ])
        original = frame.copy(deep=True)
        row = self.lab.detect_defensive_transitions(frame, "Home", 8, 8).iloc[0]
        self.assertEqual((row.outcome, row.opp_events, row.recovered), ("Shot conceded", 3, False))
        self.assertAlmostEqual(row.opp_xT, .5)
        row = self.lab.detect_defensive_transitions(frame, "Home", 7, 8).iloc[0]
        self.assertEqual((row.outcome, row.opp_events), ("Box entry conceded", 2))
        self.assertAlmostEqual(row.opp_xT, .2)
        row = self.lab.detect_defensive_transitions(frame, "Home", 8, 1).iloc[0]
        self.assertEqual((row.outcome, row.opp_events), ("Slowed", 1))
        pd.testing.assert_frame_equal(frame, original)

    def test_attacking_windows_include_win_and_cap_all_events(self):
        frame = self.frame([
            event("win", 100, "BallRecovery"),
            event("pass", 103, xT=.2),
            event("opponent", 104, "Goal", team="Away", xT=9),
            event("entry", 110, "Carry", xT=.4, is_box_entry_carry=True),
            event("late-shot", 111, "Goal"),
            event("foreign-shot", 105, "Goal", match=1),
            event("foreign-period", 105, "Goal", period=2),
            event("failed-tackle", 140, "Tackle", outcomeType="Unsuccessful"),
        ])
        result = self.lab.detect_attacking_transitions(frame, "Home", 10, 8)
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual((row.outcome, row.own_events, row.shot), ("Box entry", 3, False))
        self.assertAlmostEqual(row.xT_created, .6)
        self.assertEqual(self.lab.detect_attacking_transitions(frame, "Home", 11, 8).iloc[0].outcome, "Shot")
        self.assertEqual(self.lab.detect_attacking_transitions(frame, "Home", 10, 3).iloc[0].own_events, 2)

    def test_multimatch_load_assigns_unique_event_ids_and_preserves_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, rows in (("whoscored_Alpha_all_events.csv", [event("a", 61), event("b", 60)]),
                               ("scoresway_Beta_all_events.csv", [event("c", 60)])):
                path = Path(directory) / name
                pd.DataFrame(rows).to_csv(path, index=False)
                paths.append(str(path.resolve()))
            state = dict(tl_multi_mode=True, tl_selected_matches=paths,
                         multi_scraped_csv_paths=paths)
            fake = SimpleNamespace(session_state=state,
                                   expander=lambda *a, **k: unittest.mock.MagicMock(),
                                   toggle=lambda *a, **k: True,
                                   multiselect=lambda *a, **k: paths)
            with patch.dict(self.lab._load_matches.__globals__, st=fake, _sample_paths=lambda: []):
                merged, labels = self.lab._load_matches()
            self.assertEqual(labels, ["Alpha", "Beta"])
            self.assertEqual(merged.id.tolist(), ["b", "a", "c"])
            self.assertEqual(merged.event_id.tolist(), [0, 1, 2])
            self.assertEqual(merged.match_id.tolist(), [0, 0, 1])
            self.assertEqual(merged.source_csv.tolist(), [paths[0], paths[0], paths[1]])

    def test_pooled_style_metrics_use_relevant_matches_and_weighted_counts(self):
        # Ledger: four passes (.2, -.1, .4, 0), one carry, one corner,
        # two shots (one from corner), two box entries, one third entry.
        # PPDA: three opponent passes / two defensive actions = 1.5.
        rows = [
            event("p1", 60, xT=.2, is_long_ball=True, is_box_entry_pass=True,
                  is_final_third_entry_pass=True, pitch_zone="Left Wing", depth_zone="Attacking Third"),
            event("p2", 90, xT=-.1),
            event("carry", 120, "Carry", is_box_entry_carry=True, pitch_zone="Right Wing"),
            event("corner", 150, "CornerAwarded"), event("shot1", 155, "Goal", depth_zone="Attacking Third"),
            event("tackle", 200, "Tackle", x=40),
            event("opp1", 300, team="Away", x=40, depth_zone="Attacking Third"),
            event("opp2", 330, team="Away", x=60, depth_zone="Attacking Third"),
            event("p3", 60, match=1, xT=.4), event("p4", 90, match=1),
            event("shot2", 130, "SavedShot", match=1),
            event("foul", 200, "Foul", match=1, x=50, outcomeType="Unsuccessful"),
            event("opp3", 300, match=1, team="Away", x=50),
            event("unrelated", 60, match=2, team="Third", depth_zone="Attacking Third", x=80),
        ]
        dims, raw = self.lab.compute_style_metrics(self.frame(rows), "Home")
        expected = dict(matches_analyzed=2, passes_total=4, passes_per_match=2,
                        box_entries=2, box_entries_per_match=1, ft_entries=1,
                        ft_entries_per_match=.5, shots=2, shots_per_match=1,
                        set_piece_count=1, set_piece_shots=1, set_piece_shot_pct=50,
                        penetration_actions=6, final_third_penetration_pct=50,
                        field_tilt_pct=50, direct_passes_pct=25,
                        in_possession_actions=7, wide_in_possession_actions=2,
                        wide_in_possession_action_pct=28.6, xT_per_pass=.15,
                        ppda=1.5, ppda_opponent_passes=3, ppda_defensive_actions=2,
                        events_total=10, events_per_match=5)
        self.assertEqual({key: raw[key] for key in expected}, expected)
        self.assertEqual(dims, {"Possession\nControl": 50, "Pressing\nIntensity": 92.5,
                               "Directness": 75, "Wide Play": 28.6,
                               "Final Third\nPenetration": 100,
                               "Set Piece\nReliance": 50, "Transition\nThreat": 0})

    def test_playlist_ranking_and_trace_window_keep_match_identity(self):
        frame = self.frame([
            event("win", 60, "BallRecovery"),
            event("entry", 62, xT=.2, is_box_entry_pass=True),
            event("shot", 65, "Goal"),
            event("restart", 90, is_corner=True, xT=-.2),
            event("high", 62, "Carry", match=1, xT=.8),
            event("foreign-period", 62, "Goal", period=2),
            event("foreign-team", 62, team="Away", xT=9),
        ])
        rows = self.lab._playlist_rows(frame, "Home", 8, 8, 10, 8)
        self.assertEqual(set(rows.playlist), {"Attacking Transition", "xT Passes And Carries", "Box Entries", "Restarts"})
        threat = rows[rows.playlist.eq("xT Passes And Carries")]
        self.assertEqual(threat.id.tolist(), ["high", "entry"])
        self.assertEqual(threat.score.tolist(), [.8, .2])
        attack = rows[rows.playlist.eq("Attacking Transition")].iloc[0]
        self.assertAlmostEqual(attack.score, 4.7)
        # Transition summaries omit event_seconds; playlist must restore it.
        self.assertEqual((attack.event_seconds, attack.period_order), (60, 1))
        window = self.lab._event_window(frame, attack, before=0, after=5)
        self.assertEqual(window.id.tolist(), ["win", "entry", "foreign-team", "shot"])
        self.assertEqual(rows[rows.playlist.eq("Restarts")].iloc[0].score, 0)

    def test_trace_flips_both_axes_for_opponent_and_clamps_coordinates(self):
        self.assertEqual(self.lab._trace_coordinates(dict(x=20, y=30, endX=70, endY=80, team="Away"), "Home"),
                         (80, 70, 30, 20))
        self.assertEqual(self.lab._trace_coordinates(dict(x=-5, y=120, endX=None, endY="bad", team="Home"), "Home"),
                         (0, 100, 0, 100))

    def test_progressive_distance_must_count_as_transition_progression(self):
        # Regression: progressive distances are metres, with legacy booleans too.
        frame = self.frame([event("loss", 60, "Dispossessed"),
                            event("progressive", 62, team="Away", prog_pass=12)])
        self.assertEqual(self.lab.detect_defensive_transitions(frame, "Home").iloc[0].outcome,
                         "Progression conceded")

    def test_multimatch_team_selector_must_include_later_opponents(self):
        frame = self.frame([event("first", 60),
                            event("later", 60, match=1, team="Third", awayTeam="Third")])
        self.assertEqual(set(self.lab._team_names(frame)), {"Home", "Away", "Third"})

    def test_video_cache_identity_tracks_source_and_saved_setup_not_active_session(self):
        paths = [str(ROOT / "project-a.csv"), str(ROOT / "project-b.csv")]
        setup = dict(video_path="one.mp4", video2_path="two.mp4", split_video=True,
                     half1_time="00:00:01", half2_time="00:00:02", timeline_corrections=[])
        state = dict(match_setup_by_csv={path: dict(setup) for path in paths})
        self.lab._video_identity.__globals__["st"] = SimpleNamespace(session_state=state)
        row = dict(source_csv=paths[0], event_id=0, period="FirstHalf", minute=1, second=2)
        original = self.lab._video_identity(row)
        # New selections can reuse every event field, including event_id=0.
        self.assertNotEqual(original, self.lab._video_identity({**row, "source_csv": paths[1]}))
        state.update(video_path="unrelated.mp4", half1_time="00:00:09", timeline_corrections=[])
        self.assertEqual(original, self.lab._video_identity(row))
        for key, changed in (("video_path", "changed.mp4"), ("video2_path", "changed2.mp4"),
                             ("video5_path", "penalties.mp4"), ("half1_time", "00:00:03"),
                             ("half2_time", "00:00:04"), ("half5_time", "00:00:05"),
                             ("timeline_corrections", [{"period": 1, "clock": "1:00", "seconds": 2}])):
            with self.subTest(saved_setting=key):
                state["match_setup_by_csv"][paths[0]] = {**setup, key: changed}
                self.assertNotEqual(original, self.lab._video_identity(row))
        del state["match_setup_by_csv"][paths[0]]
        self.assertNotEqual(original, self.lab._video_identity(row))


class ComparisonNumericalAcceptance(unittest.TestCase):
    def setUp(self):
        self.page = page_functions(COMPARISON)

    def test_role_scores_and_top_five_have_independent_expected_values(self):
        frame = pd.DataFrame([
            event("goal", 60, "Goal", xT=-.2),
            event("key", 61, is_key_pass=True, xT=.25),
            event("tackle", 62, "Tackle"),
            event("failed", 63, "Tackle", outcomeType="Unsuccessful"),
            event("long", 64, is_long_ball=True, xT=.1),
            event("dribble", 65, "TakeOn"),
            event("threat", 66, "Carry", xT=2),
        ])
        original = frame.copy(deep=True)
        expectations = {"attacker": [100, 65, 0, 0, 2, 40, 20],
                        "midfielder": [100, 85, 65, 0, 57, 40, 20],
                        "defender": [0, 5, 100, 0, 2, 0, 20]}
        for role, expected in expectations.items():
            with self.subTest(role=role):
                self.assertEqual(self.page._score_moments(frame, role).moment_score.tolist(), expected)
        top, display = self.page._top5_moments(frame, "midfielder")
        self.assertEqual(top.id.tolist(), ["goal", "key", "tackle", "long", "dribble"])
        self.assertEqual(display.Score.tolist(), [100, 85, 65, 57, 40])
        pd.testing.assert_frame_equal(frame, original)

    def test_goalkeeper_scores_cap_distribution_below_saves(self):
        frame = pd.DataFrame([
            event("save", 60, "Save"), event("sweep", 61, "KeeperSweeper"),
            event("long", 62, is_long_ball=True, prog_pass=40),
            event("claim", 63, "Claim"), event("punch", 64, "Punch"),
            event("failed", 65, "Claim", outcomeType="Unsuccessful"),
            event("failed-long", 66, is_long_ball=True, outcomeType="Unsuccessful"),
        ])
        self.assertEqual(self.page._score_gk_moments(frame).moment_score.tolist(), [100, 90, 88, 70, 60, 0, 0])
        self.assertEqual(self.page._raw_gk(frame), {"Saves": 1, "Claiming": 1,
            "Punching": 1, "Sweeping": 1, "Distribution": 1,
            "Long Distribution": 1, "Ball Recovery": 0})

    def test_outfield_ledger_percentile_ties_and_keeper_normalization(self):
        frame = pd.DataFrame([
            event("pass", 60, xT=.3, is_key_pass=True, prog_pass=12),
            event("bad-pass", 61, xT=-.1, outcomeType="Unsuccessful"),
            event("carry", 62, "Carry", xT=.2, prog_carry=8),
            event("goal", 63, "Goal", xT=9), event("tackle", 64, "Tackle"),
            event("failed", 65, "Tackle", outcomeType="Unsuccessful"),
            event("dribble", 66, "TakeOn"), event("aerial", 67, "Aerial"),
        ])
        raw = self.page._raw_outfield(frame)
        expected = {"Defensive": 2, "Creative": 1, "Progressive": 2, "Shooting": 1,
                    "Danger": .4, "Dribbling": 1, "Aerial": 1,
                    "Pass Completion %": 50, "Involvement": 8}
        self.assertAlmostEqual(raw.pop("Danger"), expected.pop("Danger"))
        self.assertEqual(raw, expected)
        pool = {"A": {"Shooting": 0}, "B": {"Shooting": 2}, "C": {"Shooting": 2}, "D": {"Shooting": 5}}
        self.assertEqual(self.page._percentile_rank({"Shooting": 2}, pool), {"Shooting": 25})
        self.assertEqual(self.page._percentile_rank({"Shooting": 2}, {}), {"Shooting": 0})
        self.assertEqual(self.page._gk_head_to_head({"Saves": 3, "Claiming": 0}, {"Saves": 1, "Claiming": 0}),
                         ({"Saves": 100, "Claiming": 0}, {"Saves": 33, "Claiming": 0}))


class TacticalMediaAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import imageio_ffmpeg
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if not Path(cls.ffmpeg).is_file():
            raise unittest.SkipTest("FFmpeg executable unavailable; real media acceptance unverified")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.lab = page_functions(TACTICAL)
        self.page = page_functions(COMPARISON)
        for name, color in (("first", "red"), ("second", "lime")):
            subprocess.run([self.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                f"color=c=blue:s=64x48:r=12:d=4[a];color=c={color}:s=64x48:r=12:d=5[b];[a][b]concat=n=2:v=1:a=0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.root / f"{name}.mp4")],
                check=True, capture_output=True, timeout=30)
        self.state = dict(video_path=str(self.root / "first.mp4"),
                          video2_path=str(self.root / "second.mp4"), split_video=True,
                          half1_time="00:00:01", half2_time="00:00:01",
                          before_buffer=1, after_buffer=1,
                          timeline_corrections=[{"period": 2, "clock": "45:02", "seconds": 2}])
        self.csv = self.root / "active.csv"
        pd.DataFrame([event("active", 4)]).to_csv(self.csv, index=False)
        self.state["csv_path"] = str(self.csv)
        self.setup = dict(self.state)
        self.state["match_setup_by_csv"] = {str(self.csv): self.setup}
        # Keep every production-created scratch clip/list inside this test's dir.
        temp_api = SimpleNamespace(NamedTemporaryFile=lambda **kw: tempfile.NamedTemporaryFile(dir=self.root, **kw))
        for function in (self.lab._cut_tactical_clip, self.page.cut_clip):
            function.__globals__.update(st=SimpleNamespace(session_state=self.state), tempfile=temp_api)
        self.lab._cut_tactical_clip.__globals__["_get_ffmpeg"] = lambda: self.ffmpeg
        self.page.cut_clip.__globals__.update(
            get_ffmpeg=lambda: self.ffmpeg, **self.state,
            half3_time="", half4_time="", half5_time="",
            session_video=lambda period: self.state.get(f"video{period}_path") or self.state["video2_path"])

    def assert_video(self, path, seconds, channels):
        # Decode the ENTIRE export: 12 frames per second, one RGB pixel/frame.
        decoded = subprocess.run([self.ffmpeg, "-v", "error", "-i", str(path),
            "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            check=True, capture_output=True, timeout=30).stdout
        self.assertAlmostEqual(len(decoded) / 3 / 12, seconds, delta=.2)
        for at, channel in channels:
            pixel = decoded[int(at * 12) * 3:int(at * 12) * 3 + 3]
            self.assertEqual(len(pixel), 3, (path, at))
            self.assertGreater(pixel[channel], 200, (path, at, pixel))
            self.assertTrue(all(value < 40 for index, value in enumerate(pixel) if index != channel), (path, at, pixel))

    def test_real_tactical_moments_and_reel_use_correct_source_time_and_order(self):
        # 1H: marker 1 + clock 4 = 5s. 2H: marker 1 + clock 2 + correction 2 = 5s.
        # Both cuts must start at 4s (red / green); wrong source/time gives blue.
        first = self.lab._cut_tactical_clip(dict(source_csv=str(self.csv), period="FirstHalf", minute=0, second=4), 1, 1)
        second = self.lab._cut_tactical_clip(dict(source_csv=str(self.csv), period="SecondHalf", minute=45, second=2), 1, 1)
        self.assert_video(first, 2, [(.5, 0), (1.5, 0)])
        self.assert_video(second, 2, [(.5, 1), (1.5, 1)])
        reel = self.lab._concat_tactical_clips([second, first])
        self.assert_video(reel, 4, [(.5, 1), (1.5, 1), (2.5, 0), (3.5, 0)])
        self.assertEqual(self.lab._concat_tactical_clips([first]), first)
        with self.assertRaisesRegex(ValueError, "No clips"):
            self.lab._concat_tactical_clips([])

    def test_real_comparison_top_moments_reel_uses_ranking_and_saved_buffers(self):
        frame = pd.DataFrame([event("lower", 4, "TakeOn", period="FirstHalf"),
                              event("higher", 2702, "Goal", period="SecondHalf")])
        top, _ = self.page._top5_moments(frame, "attacker")
        self.assertEqual(top.id.tolist(), ["higher", "lower"])
        reel = self.page._generate_reel(top)
        self.assert_video(reel, 4, [(.5, 1), (1.5, 1), (2.5, 0), (3.5, 0)])

    def test_missing_marker_and_source_raise_actionable_errors(self):
        with self.assertRaisesRegex(ValueError, "kick-off.*period 3"):
            self.lab._cut_tactical_clip(dict(source_csv=str(self.csv), period="FirstPeriodOfExtraTime", minute=90, second=2))
        self.setup["video_path"] = str(self.root / "missing.mp4")
        with self.assertRaisesRegex(ValueError, "No video file loaded"):
            self.lab._cut_tactical_clip(dict(source_csv=str(self.csv), period="FirstHalf", minute=0, second=2))

    def test_tactical_cut_near_start_must_end_at_requested_post_event_time(self):
        # Event is at video 1s. Requested [-2,3] clamps to [0,3], not [0,5].
        self.setup["half1_time"] = "00:00:00"
        path = self.lab._cut_tactical_clip(dict(source_csv=str(self.csv), period="FirstHalf", minute=0, second=1), 3, 2)
        self.assert_video(path, 3, [(.5, 2)])

    def load_project_matches(self, penalties=False):
        paths = [str((self.root / "project-a.csv").resolve()), str((self.root / "project-b.csv").resolve())]
        for index, path in enumerate(paths):
            if penalties:
                # Different ORIGINAL first-kick anchors for each project. The
                # displayed rows below will deliberately omit these first kicks.
                anchor = 7270 if index == 0 else 7340
                rows = [event("first-kick", anchor, "PenaltyMissed", period=5),
                        event("later-kick", anchor + 3, "PenaltyScored", period=5)]
            else:
                rows = [event("loss", 2700, "Dispossessed", period=2),
                        event("win", 2702, "BallRecovery", period=2),
                        event("entry", 2703, "Carry", period=2, xT=.4, is_box_entry_carry=True),
                        event("restart", 2730, period=2, xT=.1, is_corner=True)]
            pd.DataFrame(rows).to_csv(path, index=False)
        setups = {}
        for index, path in enumerate(paths):
            video = str(self.root / ("first.mp4" if index == 0 else "second.mp4"))
            setups[path] = dict(video_path=video, video2_path=video, video5_path=video,
                split_video=True, half2_time="00:00:01" if index == 0 else "00:00:02",
                half5_time="00:00:02" if index == 0 else "00:00:01",
                timeline_corrections=[{"period": 2, "clock": "45:02", "seconds": 2 if index == 0 else 1},
                    {"period": 5, "clock": "121:13" if index == 0 else "122:23", "seconds": 1 if index == 0 else 2}])
        # Poison the active setup: only the saved per-project map can produce
        # the correct source/timestamps. Readiness must ignore this missing file.
        self.state.update(csv_path=str(self.root / "unrelated.csv"),
                          video_path=str(self.root / "missing-active.mp4"),
                          video2_path=str(self.root / "missing-active.mp4"),
                          half2_time="00:00:08", half5_time="00:00:08",
                          timeline_corrections=[], match_setup_by_csv=setups,
                          multi_scraped_csv_paths=paths, tl_selected_matches=paths, tl_multi_mode=True)
        fake = SimpleNamespace(session_state=self.state,
            expander=lambda *a, **k: unittest.mock.MagicMock(), toggle=lambda *a, **k: True,
            multiselect=lambda *a, **k: paths)
        with patch.dict(self.lab._load_matches.__globals__, st=fake, _sample_paths=lambda: []):
            merged, _ = self.lab._load_matches()
        return paths, setups, merged

    def test_two_project_moments_and_reel_use_saved_markers_corrections_and_videos(self):
        paths, _, frame = self.load_project_matches()
        rows = self.lab._playlist_rows(frame, "Home", 8, 8, 10, 8)
        self.assertEqual(set(rows.playlist), {"Defensive Transition", "Attacking Transition",
                         "xT Passes And Carries", "Box Entries", "Restarts"})
        for _, row in rows.iterrows():
            self.assertEqual(row.source_csv, paths[int(row.match_id)])
            self.assertTrue(self.lab._video_ready(row), row.to_dict())
        moments = rows[rows.playlist.eq("Attacking Transition")].sort_values("match_id")
        clips = []
        for channel, (_, row) in enumerate(moments.iterrows()):
            # A: marker 1 + clock 2 + correction 2; B: 2 + 2 + 1.
            self.assertEqual(self.lab._video_timestamp(row), 5)
            path = self.lab._cut_tactical_clip(row, 1, 1)
            self.assert_video(path, 2, [(.5, channel), (1.5, channel)])
            clips.append(path)
        self.assert_video(self.lab._concat_tactical_clips(clips[::-1]), 4,
                          [(.5, 1), (1.5, 1), (2.5, 0), (3.5, 0)])

    def test_missing_project_setup_and_unknown_row_identity_refuse_export(self):
        paths, setups, frame = self.load_project_matches()
        del setups[paths[1]]
        row = frame[frame.source_csv.eq(paths[1])].iloc[0]
        self.assertFalse(self.lab._video_ready(row))
        with patch.dict(self.lab._cut_tactical_clip.__globals__, subprocess=SimpleNamespace(run=unittest.mock.Mock())):
            runner = self.lab._cut_tactical_clip.__globals__["subprocess"].run
            with self.assertRaisesRegex(ValueError, "No saved video setup for project-b.csv"):
                self.lab._cut_tactical_clip(row, 1, 1)
            with self.assertRaisesRegex(ValueError, "no source CSV"):
                self.lab._cut_tactical_clip(row.drop("source_csv"), 1, 1)
            runner.assert_not_called()

    def test_standalone_fallback_requires_exact_normalized_active_csv(self):
        self.state.pop("match_setup_by_csv")
        row = dict(source_csv=os.path.join(str(self.root), ".", "active.csv"),
                   period="FirstHalf", minute=0, second=4)
        self.assertTrue(self.lab._video_ready(row))
        self.assert_video(self.lab._cut_tactical_clip(row, 1, 1), 2, [(.5, 0), (1.5, 0)])
        # Same filename, different directory is a different project, even in
        # standalone mode. The scraped fallback must obey the same identity.
        row["source_csv"] = str(self.root / "other" / "active.csv")
        self.assertFalse(self.lab._video_ready(row))
        with self.assertRaisesRegex(ValueError, "No saved video setup"):
            self.lab._cut_tactical_clip(row, 1, 1)
        self.state["scraped_csv_path"] = self.state.pop("csv_path")
        row["source_csv"] = str(self.csv)
        self.assertTrue(self.lab._video_ready(row))

    def test_shootout_timing_uses_each_original_csv_not_filtered_playlist(self):
        paths, _, frame = self.load_project_matches(penalties=True)
        filtered = frame[frame.id.eq("later-kick")].copy()
        self.lab._period_starts.__globals__.update(df=filtered, df_all=filtered)
        for channel, (_, row) in enumerate(filtered.sort_values("match_id").iterrows()):
            self.assertEqual(row.source_csv, paths[channel])
            # A: first kick marker 2 + elapsed 3 + correction 1 = 6;
            # B: first kick marker 1 + elapsed 3 + correction 2 = 6.
            self.assertEqual(self.lab._video_timestamp(row), 6)
            path = self.lab._cut_tactical_clip(row, 1, 1)
            self.assert_video(path, 2, [(.5, channel), (1.5, channel)])


if __name__ == "__main__":
    unittest.main()
