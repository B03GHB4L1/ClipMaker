"""VizorPlay xG: the chance that a shot is scored, from where and how it was taken.

The weights in config/xg_weights.json were fitted once on StatsBomb open data
(see tools/fit_xg.py) and are applied here to WhoScored / Scoresway (Opta)
events. Nothing is downloaded at run time.

What the model sees: distance and angle to goal, header or foot, volley, direct
free kick, set-piece situation, fast break, through-ball or cross assist,
one-on-one, and whether the shot followed a dribble. Opta's "big chance" flag,
which StatsBomb data lacks, is applied afterwards as a calibrated adjustment.
Defender and goalkeeper positions are not in the data, so single shots can be
off; match and season totals are far steadier. Penalties get a fixed value and
own goals and shoot-out kicks get none.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np
import pandas as pd

SHOT_TYPES = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"}
FEATURES = [
    "distance", "angle", "header", "header_distance", "volley", "direct_freekick", "set_piece",
    "fast_break", "through_ball", "cross", "one_on_one", "follows_dribble",
]
GOAL_HALF_WIDTH_M = 7.32 / 2
WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "xg_weights.json")


def goal_geometry(dx_m, dy_m):
    """Distance (m) to the goal centre and the angle (radians) the goal mouth fills,
    from a shot dx metres in front of the goal line and dy metres off-centre."""
    dx = np.maximum(np.asarray(dx_m, dtype=float), 0.0)
    dy = np.abs(np.asarray(dy_m, dtype=float))
    distance = np.hypot(dx, dy)
    left = np.arctan2(dy + GOAL_HALF_WIDTH_M, np.maximum(dx, 1e-6))
    right = np.arctan2(dy - GOAL_HALF_WIDTH_M, np.maximum(dx, 1e-6))
    return distance, np.abs(left - right)


def opta_geometry(x, y):
    """Opta / WhoScored coordinates: 0-100 each way, attacking towards x = 100."""
    x = pd.to_numeric(x, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")
    return goal_geometry((100 - x) * 1.05, (y - 50) * 0.68)


def _flag(frame, column):
    if column not in frame:
        return pd.Series(False, index=frame.index)
    values = frame[column]
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes"})


def _assist_kinds(frame, shots):
    """Through ball / cross for each shot, from the key pass just before it (same team)."""
    through = pd.Series(False, index=shots)
    cross = pd.Series(False, index=shots)
    if not len(shots):
        return through, cross
    key_pass = (frame["type"].astype(str).eq("Pass") & (_flag(frame, "is_key_pass") | _flag(frame, "is_assist")))
    through_flag = _flag(frame, "is_through_ball")
    cross_flag = _flag(frame, "is_cross")
    team = frame["team"].astype(str) if "team" in frame else pd.Series("", index=frame.index)
    positions = {label: pos for pos, label in enumerate(frame.index)}
    labels = list(frame.index)
    for shot in shots:
        pos = positions[shot]
        for back in range(1, 5):
            if pos - back < 0:
                break
            prev = labels[pos - back]
            if key_pass.at[prev] and team.at[prev] == team.at[shot]:
                through.at[shot] = bool(through_flag.at[prev])
                cross.at[shot] = bool(cross_flag.at[prev])
                break
    return through, cross


def shot_features(frame):
    """The model's inputs for every shot row in an Opta-style event frame, plus the
    penalty and big-chance flags. Index matches the shot rows of ``frame``."""
    types = frame["type"].astype(str) if "type" in frame else pd.Series("", index=frame.index)
    shots = frame[types.isin(SHOT_TYPES)]
    distance, angle = opta_geometry(shots.get("x"), shots.get("y"))
    header = _flag(shots, "is_header").astype(float)
    through, cross = _assist_kinds(frame, shots.index)
    out = pd.DataFrame({
        "distance": distance,
        "angle": angle,
        "header": header,
        "header_distance": header * distance,
        "volley": _flag(shots, "is_volley").astype(float),
        # On a shot, WhoScored's free-kick flag means it was shot directly from the free kick.
        "direct_freekick": (_flag(shots, "is_freekick") & ~_flag(shots, "is_penalty")).astype(float),
        "set_piece": _flag(shots, "is_corner_situation").astype(float),
        "fast_break": _flag(shots, "is_fast_break").astype(float),
        "through_ball": through.astype(float),
        "cross": cross.astype(float),
        "one_on_one": _flag(shots, "is_1on1").astype(float),
        "follows_dribble": (_flag(shots, "is_follows_dribble") | _flag(shots, "is_individual_play")).astype(float),
    }, index=shots.index)
    out["penalty"] = _flag(shots, "is_penalty")
    out["big_chance"] = _flag(shots, "is_big_chance_shot") | _flag(shots, "is_big_chance")
    out["own_goal"] = _flag(shots, "is_own_goal")
    period = shots["period"].astype(str) if "period" in shots else pd.Series("", index=shots.index)
    out["shootout"] = period.isin({"PenaltyShootout", "5"})
    return out


@lru_cache(maxsize=1)
def load_weights(path=WEIGHTS_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _sigmoid(values):
    return 1.0 / (1.0 + np.exp(-values))


def base_logits(features, weights):
    coefs = weights["coefficients"]
    total = np.full(len(features), float(weights["intercept"]))
    for name in FEATURES:
        total = total + float(coefs[name]) * features[name].to_numpy(dtype=float)
    return total


def predict(features, weights=None):
    """xG for each row of ``shot_features`` output (NaN where a shot has no value)."""
    weights = weights or load_weights()
    logits = base_logits(features, weights)
    big = weights.get("big_chance") or {}
    if big and "big_chance" in features:
        logits = logits + np.where(features["big_chance"].to_numpy(dtype=bool), big["offset_yes"], big["offset_no"])
    values = _sigmoid(logits)
    values = np.where(features["penalty"].to_numpy(dtype=bool), float(weights["penalty_xg"]), values)
    missing = np.isnan(features["distance"].to_numpy(dtype=float))
    excluded = features["own_goal"].to_numpy(dtype=bool) | features["shootout"].to_numpy(dtype=bool) | missing
    values = np.where(excluded, np.nan, values)
    return pd.Series(np.round(values, 4), index=features.index)


def add_xg(frame):
    """``frame`` with an ``xG`` column: a value for every shot, empty for other events."""
    frame = frame.copy()
    frame["xG"] = np.nan
    if "type" not in frame or "x" not in frame or "y" not in frame:
        return frame
    try:
        features = shot_features(frame)
        if len(features):
            frame.loc[features.index, "xG"] = predict(features)
    except (OSError, ValueError, KeyError) as exc:  # weights missing or malformed
        raise RuntimeError(f"VizorPlay xG could not be calculated: {exc}") from exc
    return frame


def describe():
    """One line for notes under charts."""
    weights = load_weights()
    return weights.get("label", "VizorPlay xG")


__all__ = ["FEATURES", "SHOT_TYPES", "add_xg", "describe", "goal_geometry", "load_weights", "opta_geometry",
           "predict", "shot_features"]
