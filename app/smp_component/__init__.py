import os
import streamlit.components.v1 as components

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Single component declaration — routing happens inside index.html via component_type arg
_analyst_component = components.declare_component(
    "analyst_room",
    path=_FRONTEND,
)


def penalty_shootout_map(shots, home_team, away_team, selected_idx=None, key=None,
                         light_mode=False, context_title="", context_subtitle="", context_note=""):
    return _analyst_component(
        component_type="penalty_shootout",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=820, key=key, default=None, light_mode=light_mode,
    )


def shot_map(shots, home_team, away_team, selected_idx=None,
             view="pitch", key=None, light_mode=False,
             context_title="", context_subtitle="", context_note=""):
    height_map = {
        "pitch": 460, "halfpitch": 460,
        "halfpitch_vert": 520, "goalframe": 320,
    }
    height = height_map.get(view, 460)
    return _analyst_component(
        component_type="shot_map",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, view=view,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def pass_map(passes, home_team, away_team, selected_idx=None,
             mode="player", key=None, light_mode=False,
             context_title="", context_subtitle="", context_note=""):
    height = 800 if mode == "network" else 470
    return _analyst_component(
        component_type="pass_map",
        passes=passes, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, mode=mode,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def defensive_map(actions, home_team, away_team, selected_idx=None, key=None, light_mode=False,
                  context_title="", context_subtitle="", context_note=""):
    height = 500
    return _analyst_component(
        component_type="defensive_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def dribble_carry_map(actions, home_team, away_team, selected_idx=None, key=None, light_mode=False,
                      context_title="", context_subtitle="", context_note=""):
    height = 500
    return _analyst_component(
        component_type="dribble_carry_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def build_up_map(actions, is_home, selected_idx=None, key=None, light_mode=False,
                 entry_mode="", height=520,
                 context_title="", context_subtitle="", context_note=""):
    return _analyst_component(
        component_type="build_up_map",
        actions=actions,
        is_home=bool(is_home),
        selected_idx=selected_idx,
        entry_mode=entry_mode or "",
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height,
        key=key,
        default=None,
        light_mode=light_mode,
    )


def goalkeeper_map(actions, home_team, away_team, selected_idx=None,
                   shots_faced=False, key=None, light_mode=False,
                   context_title="", context_subtitle="", context_note=""):
    height = 520
    return _analyst_component(
        component_type="goalkeeper_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, shots_faced=shots_faced,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
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


def timeline_window(
    current_window_seconds,
    selected_before_seconds=0,
    selected_after_seconds=0,
    before_limit_seconds=180,
    after_limit_seconds=180,
    key=None,
):
    return _analyst_component(
        component_type="timeline_window",
        current_window_seconds=int(current_window_seconds or 0),
        selected_before_seconds=int(selected_before_seconds or 0),
        selected_after_seconds=int(selected_after_seconds or 0),
        before_limit_seconds=int(before_limit_seconds or 0),
        after_limit_seconds=int(after_limit_seconds or 0),
        height=170,
        key=key,
        default=None,
    )


def echarts_chart(option, height=520, key=None, light_mode=False,
                  context_title="", context_subtitle="", context_note="",
                  filename_hint="echarts_chart"):
    return _analyst_component(
        component_type="echarts_option",
        option=option or {},
        height=int(height or 520),
        context_title=context_title or filename_hint or "",
        context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        filename_hint=filename_hint or "echarts_chart",
        key=key,
        default=None,
        light_mode=light_mode,
    )


def pressing_map(press_wins, is_home_team, selected_idx=None, key=None, light_mode=False,
                 context_title="", context_subtitle="", context_note=""):
    """Render a full-pitch high-press map using ECharts (option built in analysis_core.pressing)."""
    from analysis_core.pressing import pressing_option
    option = pressing_option(press_wins, selected_idx, light_mode, context_title, context_subtitle)
    return echarts_chart(
        option,
        height=500 if context_title or context_note else 460,
        key=key,
        light_mode=light_mode,
        context_title=context_title,
        context_subtitle=context_subtitle,
        context_note=context_note,
        filename_hint="pressing_map",
    )
