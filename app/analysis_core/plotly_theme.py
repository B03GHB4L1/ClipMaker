"""The colours Streamlit's light chart theme gave Plotly figures.

In the classic workspace, Plotly Express figures were built against
Streamlit's placeholder template (#000001...) and Streamlit's browser code
swapped in its light-theme palette. Native figures are built against a
template with those palette colours directly.
"""
from __future__ import annotations

from contextlib import contextmanager

# Streamlit light theme: blue80, blue40, red80, red40, blueGreen80, green40,
# orange80, orange50, purple80, gray40.
CATEGORICAL = ["#0068c9", "#83c9ff", "#ff2b2b", "#ffabab", "#29b09d", "#7defa1", "#ff8700", "#ffd16a",
               "#6d3fc0", "#d5dae5"]
# blue10 ... blue100
SEQUENTIAL = ["#e4f5ff", "#c7ebff", "#a6dcff", "#83c9ff", "#60b4ff", "#3d9df3", "#1c83e1", "#0068c9",
              "#0054a3", "#004280"]
# red100 ... red30, blue30 ... blue100
DIVERGING = ["#7d353b", "#bd4043", "#ff4b4b", "#ff8c8c", "#ffc7c7", "#a6dcff", "#60b4ff", "#1c83e1",
             "#0054a3", "#004280"]

# Streamlit's placeholder codes (streamlit/elements/lib/streamlit_plotly_theme.py).
PLACEHOLDERS = {f"#{index:06d}": color for index, color in enumerate(CATEGORICAL, 1)}
PLACEHOLDERS.update({f"#{index:06d}": color for index, color in enumerate(SEQUENTIAL, 11)})
PLACEHOLDERS.update({f"#{index:06d}": color for index, color in enumerate(DIVERGING, 21)})


def _scale(colors):
    return [[index / (len(colors) - 1), color] for index, color in enumerate(colors)]


def template():
    import plotly.graph_objects as go
    return go.layout.Template(layout=dict(
        colorway=CATEGORICAL,
        colorscale=dict(sequential=_scale(SEQUENTIAL), sequentialminus=_scale(SEQUENTIAL), diverging=_scale(DIVERGING)),
    ))


@contextmanager
def streamlit_palette():
    """Build Plotly (Express) figures with the classic light-theme palette."""
    import plotly.io as pio
    pio.templates["vizorplay_light"] = template()
    previous = pio.templates.default
    pio.templates.default = "vizorplay_light"
    try:
        yield
    finally:
        pio.templates.default = previous


def replace_placeholders(value):
    """Map Streamlit placeholder colours to the colours its browser code drew."""
    if isinstance(value, str):
        return PLACEHOLDERS.get(value.lower(), value)
    if isinstance(value, dict):
        return {key: replace_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(item) for item in value]
    return value
