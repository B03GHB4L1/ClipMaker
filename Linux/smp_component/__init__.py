import os
import streamlit.components.v1 as components

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Single component declaration — routing happens inside index.html via component_type arg
_analyst_component = components.declare_component(
    "analyst_room",
    path=_FRONTEND,
)


def penalty_shootout_map(shots, home_team, away_team, selected_idx=None, key=None):
    """
    Penalty shootout view: goalframe centre, home circles left, away circles right.
    Clicking a player circle returns [df_idx, timestamp].
    """
    return _analyst_component(
        component_type="penalty_shootout",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=820, key=key, default=None,
    )


def shot_map(shots, home_team, away_team, selected_idx=None,
             view="pitch", key=None):
    height_map = {
        "pitch": 460, "halfpitch": 460,
        "halfpitch_vert": 520, "goalframe": 320,
    }
    height = height_map.get(view, 460)
    return _analyst_component(
        component_type="shot_map",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, view=view,
        height=height, key=key, default=None,
    )


def pass_map(passes, home_team, away_team, selected_idx=None,
             mode="player", key=None):
    height = 800 if mode == "network" else 700
    return _analyst_component(
        component_type="pass_map",
        passes=passes, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, mode=mode,
        height=height, key=key, default=None,
    )


def defensive_map(actions, home_team, away_team, selected_idx=None, key=None):
    height = 700
    return _analyst_component(
        component_type="defensive_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=height, key=key, default=None,
    )


def dribble_carry_map(actions, home_team, away_team, selected_idx=None, key=None):
    height = 700
    return _analyst_component(
        component_type="dribble_carry_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=height, key=key, default=None,
    )


def build_up_map(actions, is_home, key=None):
    return _analyst_component(
        component_type="build_up_map",
        actions=actions,
        is_home=bool(is_home),
        height=260,
        key=key,
        default=None,
    )


def goalkeeper_map(actions, home_team, away_team, selected_idx=None,
                   shots_faced=False, key=None):
    height = 520
    return _analyst_component(
        component_type="goalkeeper_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, shots_faced=shots_faced,
        height=height, key=key, default=None,
    )


def roi_selector(frame_b64, frame_w, frame_h, existing_roi=None, key=None):
    """
    Interactive ROI selector — displays a video frame as a canvas the user can
    click-and-drag on to draw a rectangle.  Returns {x, y, w, h} in image-pixel
    coordinates when the user finishes drawing, or None if no draw has happened yet.
    """
    est_h = min(600, max(280, int(frame_h * 640 / max(frame_w, 1)) + 50))
    return _analyst_component(
        component_type="roi_selector",
        frame_b64=frame_b64,
        frame_w=frame_w,
        frame_h=frame_h,
        existing_roi=existing_roi or {},
        height=est_h,
        key=key,
        default=None,
    )
