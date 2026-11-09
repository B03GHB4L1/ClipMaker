"""Load a project's match CSV into the frames the analysis views use.

Moved unchanged from the Analyst Room's data-loading block so the classic page
and the native API compute from the same code.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

SHOT_TYPES = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost",
              "BlockedShot", "AttemptSaved", "Attempt"}

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4,
    "PenaltyShootout": 5,
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
}

DEF_ACTIONS = {"Tackle", "Interception", "Clearance", "Aerial", "Block",
               "Challenge", "Dispossessed", "Error"}

GK_ACTIONS = {"Punch", "Claim", "KeeperSweeper", "KeeperPickup", "PenaltyFaced"}


def defensive_actions_df(source_df):
    defensive = source_df[source_df["type"].isin(DEF_ACTIONS)].copy()
    if defensive.empty:
        return defensive.reset_index(drop=True)

    type_series = defensive["type"].astype(str)
    if "depth_zone" in defensive.columns:
        depth_series = defensive["depth_zone"].astype(str)
    else:
        depth_series = pd.Series("", index=defensive.index)

    # Final-third aerials are usually attacking headed shots/passes, not defensive actions.
    attacking_header_actions = type_series.eq("Aerial") & depth_series.eq("Attacking Third")
    return defensive[~attacking_header_actions].copy().reset_index(drop=True)


def resolve_event_team_names(df):
    from team_names import resolve_home_away
    if "team" not in df.columns:
        return "", ""
    event_teams = [str(team) for team in df["team"].dropna().astype(str).unique().tolist() if str(team)]
    if len(event_teams) < 2:
        return tuple((event_teams + ["", ""])[:2])
    home_label = str(df["homeTeam"].dropna().iloc[0]) if "homeTeam" in df.columns and not df["homeTeam"].dropna().empty else ""
    away_label = str(df["awayTeam"].dropna().iloc[0]) if "awayTeam" in df.columns and not df["awayTeam"].dropna().empty else ""
    return resolve_home_away(home_label, away_label, event_teams)


def _reattribute_own_goals(shots, home_team, away_team):
    if "is_own_goal" in shots.columns and home_team and away_team:
        own_goal = shots["is_own_goal"].astype(str).str.lower().isin(["true", "1", "yes"])
        home_own_goal = own_goal & (shots["team"] == home_team)
        away_own_goal = own_goal & (shots["team"] == away_team)
        shots.loc[home_own_goal, "team"] = away_team
        shots.loc[away_own_goal, "team"] = home_team


@dataclass
class AnalystFrames:
    """The Analyst Room's prepared frames for one match."""

    df_all: pd.DataFrame
    home_team: str
    away_team: str
    shots_df: pd.DataFrame
    pso_shots_df: pd.DataFrame
    passes_df: pd.DataFrame
    def_df: pd.DataFrame
    dribble_carry_df: pd.DataFrame
    gk_df: pd.DataFrame
    source: str = ""
    extras: dict = field(default_factory=dict)

    def summary(self) -> dict:
        periods = []
        if "period" in self.df_all.columns:
            periods = [str(p) for p in self.df_all["period"].dropna().unique().tolist()]
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "event_count": int(len(self.df_all) + len(self.pso_shots_df)),
            "periods": periods,
            "has_penalty_shootout": not self.pso_shots_df.empty,
            "counts": {
                "shots": int(len(self.shots_df)),
                "passes": int(len(self.passes_df)),
                "defensive_actions": int(len(self.def_df)),
                "dribbles_carries": int(len(self.dribble_carry_df)),
                "goalkeeper_actions": int(len(self.gk_df)),
            },
        }


def build_analyst_frames(raw: pd.DataFrame, source: str = "") -> AnalystFrames:
    """Prepare a raw match CSV frame exactly as the Analyst Room does."""
    from project_analysis import analysis_frame
    df_all = analysis_frame(raw)
    # The selected CSV is the source of truth; use event team names for filters/maps.
    home_team, away_team = resolve_event_team_names(df_all)
    if "period" in df_all.columns:
        pso_shots_df = df_all[df_all["period"] == "PenaltyShootout"].copy()
    else:
        pso_shots_df = pd.DataFrame()
    pso_shots_df = pso_shots_df[pso_shots_df["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True) \
        if not pso_shots_df.empty else pso_shots_df
    if "period" in df_all.columns:
        df_all = df_all[df_all["period"] != "PenaltyShootout"].copy()
    shots_df = df_all[df_all["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True)
    passes_df = df_all[df_all["type"] == "Pass"].copy().reset_index(drop=True)
    def_df = defensive_actions_df(df_all)
    dribble_carry_df = df_all[df_all["type"].isin({"TakeOn", "Carry"})].copy().reset_index(drop=True)
    gk_df = df_all[df_all["type"].isin(GK_ACTIONS)].copy().reset_index(drop=True)
    # Re-attribute own goals to the benefiting team so all filtering/display is correct
    _reattribute_own_goals(shots_df, home_team, away_team)
    _reattribute_own_goals(pso_shots_df, home_team, away_team)
    return AnalystFrames(df_all, home_team, away_team, shots_df, pso_shots_df, passes_df,
                         def_df, dribble_carry_df, gk_df, source=source)


class FrameCache:
    """Thread-safe LRU of prepared frames keyed by CSV identity.

    The key uses the file's path, size and modification time, not the
    project's ``updated_at``: saving UI state must not force a reload, while
    re-importing or re-scraping a CSV must.
    """

    def __init__(self, capacity: int = 4, loader=None):
        self.capacity = capacity
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._loader = loader
        self.loads = 0

    @staticmethod
    def identity(csv_path: str):
        path = Path(csv_path)
        stat = path.stat()
        return (os.path.normcase(str(path.resolve())), stat.st_size, stat.st_mtime_ns)

    def _load(self, csv_path: str) -> AnalystFrames:
        if self._loader:
            return self._loader(csv_path)
        from clipmaker_core import read_csv_safe
        return build_analyst_frames(read_csv_safe(csv_path), source=csv_path)

    def get(self, csv_path: str) -> AnalystFrames:
        if not csv_path or not Path(csv_path).is_file():
            raise ValueError("Scrape or import a match before opening an analytical workspace.")
        key = self.identity(csv_path)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        frames = self._load(csv_path)  # outside the lock: loads can take seconds
        with self._lock:
            self.loads += 1
            self._items[key] = frames
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)
        return frames
