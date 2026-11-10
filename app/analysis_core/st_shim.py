"""A stand-in for the parts of Streamlit the Tactical Lab tab code calls.

The classic tab functions run unchanged against this recorder. Instead of
drawing, it records each element (in call order, which matches Streamlit's
layout order for these tabs) and each control with its key, range or options.
Controls take their values from the request, validated like Streamlit would.
"""
from __future__ import annotations

import json
from contextlib import contextmanager


class StopRender(Exception):
    """Raised by st.stop(); ends the tab render early, as in Streamlit."""


def _json(value):
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


class _Slot:
    """A column, expander or container: draws into the same recorder."""

    def __init__(self, recorder):
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._recorder, name)


class Recorder:
    def __init__(self, session_state):
        self.session_state = session_state
        self.elements = []

    # ── text and messages ────────────────────────────────────────────────
    def _text(self, kind, body):
        self.elements.append({"kind": kind, "value": str(body)})

    def subheader(self, body, *args, **kwargs):
        self._text("Subheader", body)

    def caption(self, body, *args, **kwargs):
        self._text("Caption", body)

    def markdown(self, body, *args, unsafe_allow_html=False, **kwargs):
        self.elements.append({"kind": "Markdown", "value": str(body), "html": bool(unsafe_allow_html)})

    def info(self, body, *args, **kwargs):
        self._text("Info", body)

    def warning(self, body, *args, **kwargs):
        self._text("Warning", body)

    def error(self, body, *args, **kwargs):
        self._text("Error", body)

    def success(self, body, *args, **kwargs):
        self._text("Success", body)

    def divider(self, *args, **kwargs):
        self.elements.append({"kind": "Divider"})

    # ── data ─────────────────────────────────────────────────────────────
    def metric(self, label, value, delta=None, help=None, *args, **kwargs):
        self.elements.append({"kind": "Metric", "label": str(label), "value": str(value),
                              "delta": str(delta or ""), "help": str(help or "")})

    def plotly_chart(self, figure, *args, config=None, **kwargs):
        spec = json.loads(figure.to_json())
        self.elements.append({"kind": "plotly", "figure": spec, "config": _json(config or {})})

    def dataframe(self, data, *args, **kwargs):
        rows = json.loads(data.to_json(orient="values", date_format="iso"))
        self.elements.append({"kind": "Dataframe", "columns": [str(c) for c in data.columns], "rows": rows})

    def video(self, *args, **kwargs):
        pass  # Native clips are cut through the clip endpoint.

    def download_button(self, *args, **kwargs):
        pass

    # ── layout ───────────────────────────────────────────────────────────
    def columns(self, spec, *args, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Slot(self) for _ in range(count)]

    def expander(self, label, *args, **kwargs):
        return _Slot(self)

    def container(self, *args, **kwargs):
        return _Slot(self)

    @contextmanager
    def spinner(self, *args, **kwargs):
        yield

    # ── controls ─────────────────────────────────────────────────────────
    def slider(self, label, min_value=None, max_value=None, value=None, *args, key=None, **kwargs):
        default = min_value if value is None else value
        current = self.session_state.get(key, default) if key else default
        try:
            current = int(current) if isinstance(default, int) else float(current)
        except (TypeError, ValueError):
            current = default
        if not min_value <= current <= max_value:
            current = default
        if key:
            self.session_state[key] = current
        self.elements.append({"kind": "Slider", "key": key, "label": str(label), "min": min_value,
                              "max": max_value, "value": current})
        return current

    def selectbox(self, label, options, index=0, format_func=str, *args, key=None, **kwargs):
        options = list(options)
        current = self.session_state.get(key) if key else None
        if current not in options:
            current = options[index] if options and index is not None else None
        if key:
            self.session_state[key] = current
        self.elements.append({"kind": "Selectbox", "key": key, "label": str(label),
                              "options": [str(format_func(option)) for option in options],
                              "values": _json(options), "value": _json(current)})
        return current

    def toggle(self, label, value=False, *args, key=None, **kwargs):
        return bool(self.session_state.get(key, value)) if key else value

    def multiselect(self, label, options, *args, key=None, **kwargs):
        return list(self.session_state.get(key, [])) if key else []

    def button(self, label, *args, key=None, disabled=False, **kwargs):
        self.elements.append({"kind": "Button", "key": key, "label": str(label), "disabled": bool(disabled)})
        return False  # Actions such as cutting clips go through their own endpoint.

    def rerun(self):
        pass

    def stop(self):
        raise StopRender()

    # ── decorators ───────────────────────────────────────────────────────
    @staticmethod
    def cache_data(*args, **kwargs):
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return lambda function: function
