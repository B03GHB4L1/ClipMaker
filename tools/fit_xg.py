"""Fit VizorPlay's xG weights (app/config/xg_weights.json).

Run once by a maintainer, not by the app. Inputs:
  --statsbomb DIR   StatsBomb open-data event files (data/events/<match>.json),
                    https://github.com/statsbomb/open-data (free; credit StatsBomb).
  --whoscored DIR   WhoScored CSVs scraped by VizorPlay, used to calibrate Opta's
                    big-chance flag and to check the result.

The model is a logistic regression on features both sources share (see
app/xg_model.py). StatsBomb has no big-chance flag, so afterwards big-chance
shots are shifted to Opta's long-run big-chance conversion rate and the other
shots are shifted the opposite way so a match's total xG stays the same.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import xg_model  # noqa: E402

YARD = 0.9144
# Opta reports roughly 38% of big chances scored over long runs of data; a
# deliberate, documented assumption (StatsBomb data cannot measure it).
BIG_CHANCE_TARGET = 0.38
PENALTY_XG = 0.76


def statsbomb_shots(folder):
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            events = json.load(handle)
        by_id = {event["id"]: event for event in events}
        match = os.path.splitext(os.path.basename(path))[0]
        for event in events:
            if event.get("type", {}).get("name") != "Shot":
                continue
            shot = event["shot"]
            kind = shot.get("type", {}).get("name")
            if event.get("period") == 5 or kind == "Kick Off":
                continue
            x, y = event["location"][:2]
            key = by_id.get(shot.get("key_pass_id")) or {}
            pass_ = key.get("pass", {})
            technique = shot.get("technique", {}).get("name", "")
            pattern = event.get("play_pattern", {}).get("name", "")
            rows.append({
                "match": match,
                "dx": (120 - x) * YARD,
                "dy": (y - 40) * YARD,
                "header": shot.get("body_part", {}).get("name") == "Head",
                "volley": technique in {"Volley", "Half Volley"},
                "direct_freekick": kind == "Free Kick",
                "penalty": kind == "Penalty",
                "set_piece": kind != "Free Kick" and pattern in {"From Corner", "From Free Kick"},
                "fast_break": pattern == "From Counter",
                "through_ball": bool(pass_.get("through_ball")) or pass_.get("technique", {}).get("name") == "Through Ball",
                "cross": bool(pass_.get("cross")),
                "one_on_one": bool(shot.get("one_on_one")),
                "follows_dribble": bool(shot.get("follows_dribble")),
                "goal": shot.get("outcome", {}).get("name") == "Goal",
                "statsbomb_xg": shot.get("statsbomb_xg"),
            })
    frame = pd.DataFrame(rows)
    distance, angle = xg_model.goal_geometry(frame["dx"], frame["dy"])
    frame["distance"], frame["angle"] = distance, angle
    for name in ("header", "volley", "direct_freekick", "set_piece", "fast_break", "through_ball", "cross",
                 "one_on_one", "follows_dribble"):
        frame[name] = frame[name].astype(float)
    frame["header_distance"] = frame["header"] * frame["distance"]
    return frame


def scores(goal, prob):
    return {"log_loss": round(float(log_loss(goal, prob)), 4), "brier": round(float(brier_score_loss(goal, prob)), 4),
            "auc": round(float(roc_auc_score(goal, prob)), 4)}


def fit(frame):
    model = LogisticRegression(C=10.0, max_iter=2000)
    model.fit(frame[xg_model.FEATURES], frame["goal"])
    return model


def solve_offset(logits, target):
    """The logit shift that makes the mean probability equal ``target``."""
    low, high = -10.0, 10.0
    for _ in range(80):
        mid = (low + high) / 2
        if np.mean(1 / (1 + np.exp(-(logits + mid)))) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--statsbomb", required=True)
    parser.add_argument("--whoscored", required=True)
    parser.add_argument("--out", default=xg_model.WEIGHTS_PATH)
    args = parser.parse_args()

    shots = statsbomb_shots(args.statsbomb)
    open_play = shots[~shots["penalty"]].reset_index(drop=True)
    penalties = shots[shots["penalty"]]
    print(f"StatsBomb: {shots['match'].nunique()} matches, {len(open_play)} non-penalty shots, {len(penalties)} penalties")

    # Out-of-sample check, grouped by match so no match is in both halves.
    predicted = np.zeros(len(open_play))
    for train, test in GroupKFold(n_splits=5).split(open_play, open_play["goal"], open_play["match"]):
        predicted[test] = fit(open_play.iloc[train]).predict_proba(open_play.iloc[test][xg_model.FEATURES])[:, 1]
    check = {"vizorplay_cross_validated": scores(open_play["goal"], predicted)}
    known = open_play["statsbomb_xg"].notna()
    check["statsbomb_xg_same_shots"] = scores(open_play.loc[known, "goal"], open_play.loc[known, "statsbomb_xg"])
    print(json.dumps(check, indent=2))

    model = fit(open_play)
    weights = {
        "label": "VizorPlay xG",
        "fitted": dt.date.today().isoformat(),
        "source": "StatsBomb open data (https://github.com/statsbomb/open-data), 2015/16 men's league matches",
        "matches": int(shots["match"].nunique()),
        "shots": int(len(open_play)),
        "intercept": round(float(model.intercept_[0]), 6),
        "coefficients": {name: round(float(value), 6) for name, value in zip(xg_model.FEATURES, model.coef_[0])},
        # Too few penalties in the sample to fit; use the widely published long-run rate.
        "penalty_xg": PENALTY_XG,
        "penalties_in_sample": {"taken": int(len(penalties)), "scored": int(penalties["goal"].sum())},
        "check": check,
    }

    # Big chances: calibrated on Opta-tagged shots from WhoScored.
    frames = []
    for path in sorted(glob.glob(os.path.join(args.whoscored, "*.csv"))):
        raw = pd.read_csv(path, low_memory=False)
        features = xg_model.shot_features(raw)
        features["goal"] = raw.loc[features.index, "type"].astype(str).eq("Goal").to_numpy()
        frames.append(features)
    opta = pd.concat(frames, ignore_index=True)
    opta = opta[~opta["penalty"] & ~opta["own_goal"] & ~opta["shootout"] & opta["distance"].notna()]
    logits = xg_model.base_logits(opta, weights)
    big = opta["big_chance"].to_numpy(dtype=bool)
    base_total = float(np.sum(1 / (1 + np.exp(-logits))))
    offset_yes = solve_offset(logits[big], BIG_CHANCE_TARGET) if big.any() else 0.0
    big_total = BIG_CHANCE_TARGET * big.sum()
    rest_target = max((base_total - big_total) / max((~big).sum(), 1), 0.005)
    offset_no = solve_offset(logits[~big], rest_target) if (~big).any() else 0.0
    weights["big_chance"] = {
        "offset_yes": round(offset_yes, 6), "offset_no": round(offset_no, 6), "target_conversion": BIG_CHANCE_TARGET,
        "calibration_shots": int(len(opta)), "calibration_big_chances": int(big.sum()),
    }
    final = xg_model.predict(opta, weights)
    weights["check"]["opta_shots"] = {
        "matches": len(frames), "shots": int(len(opta)), "goals": int(opta["goal"].sum()),
        "xg_total": round(float(final.sum()), 2),
        "big_chances": int(big.sum()), "big_chance_goals": int(opta.loc[big, "goal"].sum()),
        "big_chance_mean_xg": round(float(final[big].mean()), 3) if big.any() else None,
        "other_mean_xg": round(float(final[~big].mean()), 3),
        "other_goal_rate": round(float(opta.loc[~big, "goal"].mean()), 3),
        **scores(opta["goal"], final.clip(1e-4, 1 - 1e-4)),
    }
    print(json.dumps({k: weights[k] for k in ("coefficients", "intercept", "penalty_xg", "big_chance")}, indent=2))
    print(json.dumps(weights["check"]["opta_shots"], indent=2))
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(weights, handle, indent=2)
        handle.write("\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
