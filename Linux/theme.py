"""
ClipMaker v1.2.3 — Kinetic Analyst Theme
Deep black + neon chartreuse (#DFFF00), Inter, brutalist uppercase tracking.
Reference: Kinetic Analyst dashboard mockup.
"""

import os
import re
import functools as _functools

_LOCAL_FONTS_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts", "fonts.css")
_USE_LOCAL_FONTS = os.path.exists(_LOCAL_FONTS_CSS)

FONTS_URL = "https://fonts.googleapis.com/css2?family=Iosevka+Charon+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400;1,500&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap"
ICONS_URL = "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20,500,0,0"

ICON_MAP = {
    "[OK]": "check_circle",
    "[ERR]": "cancel",
    "[X]": "close",
    "[DL]": "download",
    "[RUN]": "play_arrow",
    "[SETUP]": "tune",
    "[SHOT]": "sports_soccer",
    "[PASS]": "route",
    "[DEF]": "shield",
    "[FILTER]": "filter_alt",
    "[AI]": "smart_toy",
    "[ASK]": "chat",
    "[DEBUG]": "bug_report",
    "[FIND]": "search",
    "[SEARCH]": "search",
    "[CLIP]": "movie",
    "[RETRY]": "refresh",
    "[DATA]": "dataset",
    "[WARN]": "warning",
    "[INFO]": "info",
    "[ERROR]": "error",
    "[FAIL]": "report",
    "[MATCH]": "done_all",
    "[RESULT]": "analytics",
    "[HINT]": "lightbulb",
    "[SM]": "slow_motion_video",
    "[SB]": "tv",
    "[GOAL]": "sports_soccer",
    "[SAVE]": "sports_handball",
    "[POST]": "vertical_align_center",
    "[TKL]": "front_hand",
    "[INT]": "call_merge",
    "[CLR]": "cleaning_services",
    "[AER]": "north",
    "[BLK]": "block",
    "[CHL]": "bolt",
    "[DIS]": "do_not_disturb_on",
    "[KEY]": "key",
}

ICON_GLYPH_MAP = {
    "[OK]": "✓",
    "[ERR]": "✕",
    "[X]": "✕",
    "[DL]": "⤓",
    "[RUN]": "▶",
    "[SETUP]": "⚙",
    "[SHOT]": "◉",
    "[PASS]": "⇢",
    "[DEF]": "▣",
    "[FILTER]": "⌬",
    "[AI]": "✦",
    "[ASK]": "?",
    "[DEBUG]": "⌁",
    "[FIND]": "⌕",
    "[SEARCH]": "⌕",
    "[CLIP]": "▤",
    "[RETRY]": "↻",
    "[DATA]": "▦",
    "[WARN]": "⚠",
    "[INFO]": "ℹ",
    "[ERROR]": "✖",
    "[FAIL]": "✖",
    "[MATCH]": "✓",
    "[RESULT]": "◎",
    "[HINT]": "※",
    "[SM]": "≈",
    "[SB]": "▭",
    "[GOAL]": "◉",
    "[SAVE]": "◍",
    "[POST]": "│",
    "[TKL]": "Ⓣ",
    "[INT]": "Ⓘ",
    "[CLR]": "Ⓒ",
    "[AER]": "Ⓐ",
    "[BLK]": "Ⓑ",
    "[CHL]": "Ⓗ",
    "[DIS]": "Ⓓ",
    "[KEY]": "◆",
}

_ICON_TOKEN_PATTERN = re.compile(r"\[([A-Z]{1,})\]")

def _fonts_import():
    icon_import = f"@import url('{ICONS_URL}');"
    if _USE_LOCAL_FONTS:
        try:
            with open(_LOCAL_FONTS_CSS, "r", encoding="utf-8") as f:
                return f"{f.read()}\n{icon_import}"
        except Exception:
            pass
    return f"@import url('{FONTS_URL}');\n{icon_import}"

BG_BASE      = "#0e0e0e"
BG_SURFACE   = "#131313"
BG_ELEVATED  = "#1a1a1a"
BG_HIGH      = "#202020"
BG_HIGHEST   = "#262626"
BG_BORDER    = "#2c2c2c"

ACCENT       = "#DFFF00"   # neon chartreuse
ACCENT_DIM   = "#b8d400"
ACCENT_GLOW  = "rgba(223,255,0,0.12)"
ACCENT_SOFT  = "rgba(223,255,0,0.06)"

TEXT_PRIMARY   = "#ffffff"
TEXT_SECONDARY = "#adaaaa"
TEXT_MUTED     = "#767575"

GREEN  = "#DFFF00"
RED    = "#ff7351"
BLUE   = "#7ab4ff"

HOME_HEX = "#7ab4ff"
AWAY_HEX = "#ff7351"

LIGHT_PALETTE = {
    "BG_BASE":       "#f5f0e8",
    "BG_SURFACE":    "#fcf8f2",
    "BG_ELEVATED":   "#f0ebe2",
    "BG_HIGH":       "#e8e2d6",
    "BG_HIGHEST":    "#ddd6c8",
    "BG_BORDER":     "#c8bfb0",
    "ACCENT":        "#2f5d16",
    "ACCENT_DIM":    "#234610",
    "ACCENT_GLOW":   "rgba(47,93,22,0.18)",
    "ACCENT_SOFT":   "rgba(47,93,22,0.10)",
    "TEXT_PRIMARY":  "#111111",
    "TEXT_SECONDARY":"#444444",
    "TEXT_MUTED":    "#888888",
}

LIGHT_MODE_CSS = """
<style>
/* ══════════════════════════════════════════════════════════════════
   LIGHT MODE OVERRIDE — injected after the dark base when toggled.
   Selectors are specific enough to win without !important wars.
   ══════════════════════════════════════════════════════════════════ */

/* CSS variable overrides — fixes logo_header and all var() references */
:root {
    --cm-bg:       #f5f0e8 !important;
    --cm-surface:  #fcf8f2 !important;
    --cm-border:   #c8bfb0 !important;
    --cm-title:    #111111 !important;
    --cm-subtitle: #666666 !important;
    --cm-accent:   #2f5d16 !important;
    --cm-accent-dim: #234610 !important;
    --cm-accent-soft: rgba(47,93,22,0.10) !important;
    --cm-accent-glow: rgba(47,93,22,0.18) !important;
    --cm-icon:     #2f5d16 !important;
    --text-color:  #111111 !important;
    --background-color: #f5f0e8 !important;
}

/* Page & container backgrounds */
html, body, [class*="css"]                { color: #111111 !important; background-color: #f5f0e8 !important; }
.block-container                          { background-color: #f5f0e8 !important; }
[data-testid="stApp"]                     { background-color: #f5f0e8 !important; }
[data-testid="stAppViewBlockContainer"]   { background-color: #f5f0e8 !important; }
[data-testid="stMain"]                    { background-color: #f5f0e8 !important; }

/* Headings */
h1, h2, h3, h4, h5, h6 { color: #111111 !important; }

/* Body / markdown text */
p, .stMarkdown p, [data-testid="stMarkdownContainer"] p { color: #333333 !important; }

/* Widget labels */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"]             { color: #333333 !important; }

/* Captions */
.stCaption, [data-testid="stCaptionContainer"] p { color: #666666 !important; }

/* Topnav page links */
[data-testid="stPageLink"] a {
    background: #f0ebe2 !important;
    border-color: #c8bfb0 !important;
    color: #444444 !important;
}
[data-testid="stPageLink"] a:hover {
    border-color: #2f5d16 !important;
    color: #2f5d16 !important;
    background: rgba(47,93,22,0.10) !important;
}

/* Topnav divider */
.cm-topnav-divider { background: linear-gradient(90deg, rgba(47,93,22,0.65), transparent) !important; }

/* Inputs & textareas */
[data-baseweb="input"]                    { background: #ddd6c8 !important; border-bottom-color: #c8bfb0 !important; }
[data-baseweb="input"] input,
input, textarea                           { background: #ddd6c8 !important; border-bottom-color: #c8bfb0 !important;
                                            color: #111111 !important; }
[data-baseweb="input"] *,
[data-testid="stTextInput"] *,
[data-testid="stTextArea"] *,
[data-testid="stNumberInput"] *           { color: #111111 !important; }
[data-baseweb="input"] input::placeholder,
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
input::placeholder,
textarea::placeholder                     { color: #6f685f !important; opacity: 1 !important; }
[data-baseweb="input"]:focus-within      { border-bottom-color: #2f5d16 !important; }
input:focus, textarea:focus              { border-bottom-color: #2f5d16 !important; }

/* Select / multiselect */
[data-baseweb="select"] > div            { background: #ddd6c8 !important; border-bottom-color: #c8bfb0 !important;
                                           color: #111111 !important; }
[data-baseweb="select"] *,
[data-baseweb="select"] input,
[data-baseweb="select"] [role="combobox"],
[data-baseweb="select"] [role="button"]  { color: #111111 !important; }
[data-baseweb="select"] svg              { color: #444444 !important; fill: #444444 !important; }
[data-baseweb="tag"]                     { background: rgba(47,93,22,0.12) !important;
                                           color: #234610 !important;
                                           border-color: #2f5d16 !important; }

/* Number input */
[data-testid="stNumberInput"] input      { background: #ddd6c8 !important; border-bottom-color: #c8bfb0 !important;
                                           color: #111111 !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"]        { border-bottom-color: #c8bfb0 !important; }
.stTabs [data-baseweb="tab"]             { color: #888888 !important; }
.stTabs [data-baseweb="tab"]:hover       { color: #111111 !important; background: #e8e2d6 !important; }
.stTabs [aria-selected="true"]           { color: #234610 !important; background: rgba(47,93,22,0.10) !important;
                                           border-bottom-color: #2f5d16 !important; }

/* Expander */
[data-testid="stExpander"]              { background: #fcf8f2 !important; border-color: #c8bfb0 !important; }
[data-testid="stExpander"] summary      { color: #444444 !important; }

/* Alerts / info boxes */
.stAlert                                { background: #fcf8f2 !important; }

/* Dataframe */
[data-testid="stDataFrame"]             { background: #fcf8f2 !important; border-color: #c8bfb0 !important; }

/* Plotly figures */
.js-plotly-plot .plotly .gtitle,
.js-plotly-plot .plotly .xtitle,
.js-plotly-plot .plotly .ytitle,
.js-plotly-plot .plotly .legendtitletext,
.js-plotly-plot .plotly .legendtext,
.js-plotly-plot .plotly .xtick text,
.js-plotly-plot .plotly .ytick text,
.js-plotly-plot .plotly .annotation-text,
.js-plotly-plot .plotly .colorbar text {
    fill: #111111 !important;
    color: #111111 !important;
}
.js-plotly-plot .plotly .gridlayer path,
.js-plotly-plot .plotly .zerolinelayer path {
    stroke: rgba(80,60,30,0.16) !important;
}
.js-plotly-plot .plotly .modebar-btn svg {
    fill: #555048 !important;
}

/* Divider */
hr, [data-testid="stDivider"]           { border-color: #c8bfb0 !important; }

/* Metrics */
[data-testid="stMetric"]                { color: #111111 !important; }
[data-testid="stMetricValue"]           { color: #111111 !important; }
[data-testid="stMetricLabel"]           { color: #555555 !important; }

/* Checkbox */
[data-testid="stCheckbox"]              { color: #444444 !important; }

/* Icons */
.material-symbols-outlined,
span.material-symbols-outlined,
[class*="material-symbols"],
[data-testid="stIconMaterial"],
[data-testid="stPageLink"] svg,
[data-testid="stPageLink"] span,
[data-testid="stButton"] svg,
.stButton button svg,
button svg,
[role="button"] svg,
[data-baseweb="checkbox"] svg,
[data-baseweb="radio"] svg,
[data-testid="stToggle"] svg,
[data-testid="stCheckbox"] svg,
[data-testid="stFileUploader"] svg,
[data-testid="stDownloadButton"] svg,
.cm-icon,
span[aria-hidden="true"]                { color: #3a5000 !important;
                                          fill: #3a5000 !important;
                                          stroke: #3a5000 !important; }
[data-testid="stPageLink"] a:hover svg,
[data-testid="stPageLink"] a:hover span,
button:hover svg,
[role="button"]:hover svg               { color: #234610 !important;
                                          fill: #234610 !important;
                                          stroke: #234610 !important; }

/* Buttons and primary actions */
.stButton > button,
[data-testid="stButton"] button,
[data-testid="stDownloadButton"] button,
[data-testid="stFormSubmitButton"] button,
button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #234610 0%, #2f5d16 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 8px 18px rgba(47,93,22,0.22) !important;
}
.stButton > button *,
[data-testid="stButton"] button *,
[data-testid="stDownloadButton"] button *,
[data-testid="stFormSubmitButton"] button *,
button[kind="primary"] *,
button[data-testid="baseButton-primary"] *,
.stButton > button .material-symbols-outlined,
[data-testid="stButton"] button .material-symbols-outlined,
[data-testid="stDownloadButton"] button .material-symbols-outlined,
[data-testid="stFormSubmitButton"] button .material-symbols-outlined {
    color: #ffffff !important;
    fill: #ffffff !important;
    stroke: #ffffff !important;
}
.stButton > button svg,
[data-testid="stButton"] button svg,
[data-testid="stDownloadButton"] button svg,
[data-testid="stFormSubmitButton"] button svg,
button[kind="primary"] svg,
button[data-testid="baseButton-primary"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
    stroke: #ffffff !important;
}
.stButton > button:hover,
[data-testid="stButton"] button:hover,
[data-testid="stDownloadButton"] button:hover,
[data-testid="stFormSubmitButton"] button:hover {
    background: linear-gradient(135deg, #1f3f0f 0%, #285013 100%) !important;
    box-shadow: 0 10px 22px rgba(47,93,22,0.30) !important;
}
.stButton > button:hover *,
[data-testid="stButton"] button:hover *,
[data-testid="stDownloadButton"] button:hover *,
[data-testid="stFormSubmitButton"] button:hover *,
.stButton > button:hover svg,
[data-testid="stButton"] button:hover svg,
[data-testid="stDownloadButton"] button:hover svg,
[data-testid="stFormSubmitButton"] button:hover svg {
    color: #ffffff !important;
    fill: #ffffff !important;
    stroke: #ffffff !important;
}

/* Help / tooltip trigger buttons */
[data-testid="stTooltipHoverTarget"],
[data-testid="stWidgetLabel"] button,
[data-testid="stMarkdownContainer"] button[aria-label*="help" i],
button[aria-label*="help" i],
button[title*="help" i] {
    background: transparent !important;
    color: #2f5d16 !important;
    border: none !important;
    box-shadow: none !important;
}
[data-testid="stTooltipHoverTarget"] *,
[data-testid="stTooltipHoverTarget"] svg,
[data-testid="stWidgetLabel"] button *,
[data-testid="stWidgetLabel"] button svg,
[data-testid="stMarkdownContainer"] button[aria-label*="help" i] *,
[data-testid="stMarkdownContainer"] button[aria-label*="help" i] svg,
button[aria-label*="help" i] *,
button[aria-label*="help" i] svg,
button[title*="help" i] *,
button[title*="help" i] svg {
    color: #2f5d16 !important;
    fill: none !important;
    stroke: #2f5d16 !important;
}
[data-testid="stTooltipHoverTarget"]:hover,
[data-testid="stWidgetLabel"] button:hover,
button[aria-label*="help" i]:hover,
button[title*="help" i]:hover {
    background: #e8e2d6 !important;
    color: #234610 !important;
}

/* Tooltips, popovers, menus, and dropdown options */
[data-testid="stTooltipContent"],
[data-baseweb="tooltip"],
[data-baseweb="popover"],
[role="tooltip"],
[role="listbox"],
[data-baseweb="menu"],
[data-baseweb="popover"] > div          { background: #fcf8f2 !important;
                                          border-color: #c8bfb0 !important;
                                          color: #111111 !important; }
[data-testid="stTooltipContent"] *,
[data-baseweb="tooltip"] *,
[data-baseweb="popover"] *,
[role="tooltip"] *,
[role="listbox"] *,
[data-baseweb="menu"] *                 { color: #111111 !important; }
[role="option"],
[data-baseweb="menu"] li,
[data-baseweb="menu"] [role="option"]   { background: #fcf8f2 !important;
                                          color: #111111 !important; }
[role="option"]:hover,
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] [role="option"]:hover {
                                          background: #e8e2d6 !important;
                                          color: #111111 !important; }
[aria-selected="true"][role="option"]   { background: rgba(47,93,22,0.14) !important;
                                          color: #234610 !important; }

/* Scrollbars */
::-webkit-scrollbar-track               { background: #f5f0e8 !important; }
::-webkit-scrollbar-thumb               { background: #ddd6c8 !important; }
::-webkit-scrollbar-thumb:hover         { background: #c8bfb0 !important; }

/* Sidebar (if visible) */
section[data-testid="stSidebar"]        { background: #fcf8f2 !important;
                                          border-right-color: rgba(0,0,0,0.08) !important; }

/* ── CM component classes ── */
.cm-step-num {
    background: #2f5d16 !important;
    color: #ffffff !important;
    box-shadow: 0 0 12px rgba(47,93,22,0.28) !important;
}
.cm-step-label          { color: #234610 !important; }
.cm-log-box             { background: #e8e2d6 !important; color: #3a5000 !important;
                          border-color: #c8bfb0 !important; }
.cm-status-ready        { background: rgba(47,93,22,0.12) !important; color: #234610 !important;
                          border-left-color: #2f5d16 !important; }
.cm-status-empty        { background: #fcf8f2 !important; color: #888888 !important;
                          border-left-color: #c8bfb0 !important; }
.cm-context-bar         { background: #fcf8f2 !important; border-color: #c8bfb0 !important;
                          color: #444444 !important; }
.cm-ctx-dot-ok          { background: #2f5d16 !important; box-shadow: 0 0 6px rgba(47,93,22,0.45) !important; }
.cm-stats-bar           { background: #fcf8f2 !important; border-color: #c8bfb0 !important; }
.cm-stats-cell          { border-right-color: #c8bfb0 !important; }
.cm-stats-label         { color: #888888 !important; }
.cm-shot-panel,
.cm-event-panel         { background: #fcf8f2 !important; border-color: #c8bfb0 !important; }
.cm-shot-panel:hover,
.cm-event-panel:hover   { border-left-color: #2f5d16 !important; }
.cm-panel-title         { color: #111111 !important; }
.cm-panel-sub           { color: #888888 !important; }
.cm-detail-label        { color: #888888 !important; }
.cm-detail-value        { color: #111111 !important; }
.cm-no-data-msg         { color: #888888 !important; }
.cm-ai-box              { background: #e8e2d6 !important; color: #111111 !important;
                          border-color: #c8bfb0 !important; }
.cm-progress-label      { color: #888888 !important; }
.cm-progress-fill,
[data-testid="stProgress"] [role="progressbar"] > div,
[data-testid="stProgress"] div div div { background: #2f5d16 !important; }
.cm-footer              { color: #888888 !important; }
.cm-support-footer      { border-top-color: #c8bfb0 !important; }
.cm-support-panel       { background: #fcf8f2 !important; border-color: #c8bfb0 !important; }
.cm-support-kicker      { color: #234610 !important; }
.cm-support-title       { color: #111111 !important; }
.cm-support-copy        { color: #444444 !important; }
.cm-support-meta        { color: #888888 !important; }
.cm-support-qr-caption  { color: #888888 !important; }
.cm-support-btn         { background: linear-gradient(180deg, #234610 0%, #2f5d16 100%) !important;
                          box-shadow: 0 10px 24px rgba(47,93,22,0.20) !important; }

/* Badge colours that use dark backgrounds */
.cm-badge-goal,
.cm-badge-success,
.cm-badge-interc        { background: rgba(47,93,22,0.12) !important;
                          color: #234610 !important;
                          border-color: #2f5d16 !important; }
.cm-badge-missed        { background: #e8e2d6 !important; color: #888888 !important;
                          border-color: #c8bfb0 !important; }
.cm-badge-blocked       { background: #e8e2d6 !important; color: #666666 !important;
                          border-color: #c8bfb0 !important; }
.cm-badge-clear         { background: #e8e2d6 !important; color: #666666 !important;
                          border-color: #c8bfb0 !important; }
.cm-badge-no-data       { background: #e8e2d6 !important; color: #888888 !important;
                          border-color: #c8bfb0 !important; }

/* Inline legend/caption strings — ensure visible on light bg */
[style*="color:#767575"]   { color: #555555 !important; }
[style*="color: #767575"]  { color: #555555 !important; }
[style*="color:#adaaaa"]   { color: #555555 !important; }
[style*="color: #adaaaa"]  { color: #555555 !important; }
[style*="color:#ccc;"]     { color: #555555 !important; }
[style*="color: #ccc;"]    { color: #555555 !important; }
[style*="color:#ccc\""]    { color: #555555 !important; }
[style*="color: #ccc\""]   { color: #555555 !important; }
/* Catch inline neon-green (DFFF00) text — switch to dark green on light bg */
[style*="color:#DFFF00"],
[style*="color: #DFFF00"],
[style*="color:#dfff00"],
[style*="color: #dfff00"],
[style*="color:#b8d400"],
[style*="color: #b8d400"],
[style*="color:#9ab200"],
[style*="color: #9ab200"]  { color: #234610 !important; }
[style*="background:#DFFF00"],
[style*="background: #DFFF00"],
[style*="background:#dfff00"],
[style*="background: #dfff00"],
[style*="background:#b8d400"],
[style*="background: #b8d400"],
[style*="background:#9ab200"],
[style*="background: #9ab200"] { background: #2f5d16 !important; }
[style*="border-color:#DFFF00"],
[style*="border-color: #DFFF00"],
[style*="border-color:#dfff00"],
[style*="border-color: #dfff00"],
[style*="border-color:#b8d400"],
[style*="border-color: #b8d400"],
[style*="border-color:#9ab200"],
[style*="border-color: #9ab200"] { border-color: #2f5d16 !important; }
[style*="rgba(223,255,0"],
[style*="rgba(223, 255, 0"],
[style*="rgba(184,212,0"],
[style*="rgba(184, 212, 0"] {
    color: #234610 !important;
    border-color: #2f5d16 !important;
    box-shadow: none !important;
}
[style*="linear-gradient"][style*="223,255,0"],
[style*="linear-gradient"][style*="223, 255, 0"],
[style*="linear-gradient"][style*="184,212,0"],
[style*="linear-gradient"][style*="184, 212, 0"],
[style*="linear-gradient"][style*="#DFFF00"],
[style*="linear-gradient"][style*="#dfff00"] {
    background: linear-gradient(90deg, rgba(47,93,22,0.65), transparent) !important;
}
</style>
"""


GLOBAL_CSS = f"""
<style>
/* fonts injected dynamically by inject() */

:root {{
    --cm-sidebar-width: 18rem;
    --cm-bg: {BG_BASE};
    --cm-surface: {BG_SURFACE};
    --cm-border: {BG_BORDER};
    --cm-title: {TEXT_PRIMARY};
    --cm-subtitle: {TEXT_MUTED};
}}

/* Hide Streamlit top header bar entirely */
header[data-testid="stHeader"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] {{
    display: none !important;
    height: 0 !important;
}}

/* Navbar mode: hide Streamlit sidebar navigation entirely */
section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {{
    display: none !important;
}}

[data-testid="stPageLink"] a {{
    width: auto !important;
    display: inline-flex !important;
    display: flex !important;
    justify-content: center !important;
    align-items: center !important;
    min-height: 36px !important;
    padding: 0 14px !important;
    border: 1px solid {BG_BORDER} !important;
    background: {BG_SURFACE} !important;
    color: {TEXT_SECONDARY} !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-size: 10px !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    border-radius: 2px !important;
}}
[data-testid="stPageLink"] a:hover {{
    border-color: {ACCENT} !important;
    color: {ACCENT} !important;
    background: {ACCENT_SOFT} !important;
}}

.cm-topnav-divider {{
    height: 1px;
    background: linear-gradient(90deg, rgba(223,255,0,0.45), transparent);
    margin: 10px 0 20px 0;
}}

/* ── Reset & Base ── */
html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif !important;
    color: {TEXT_PRIMARY};
    background-color: {BG_BASE};
}}

.material-symbols-outlined {{
    font-variation-settings: 'FILL' 0, 'wght' 500, 'GRAD' 0, 'opsz' 20;
    vertical-align: text-bottom;
}}

/* ── Main container ── */
.block-container {{
    padding-top: 2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1380px !important;
    background-color: {BG_BASE} !important;
}}

/* ── Headings ── */
h1 {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 700 !important;
    font-style: normal !important;
    text-transform: uppercase !important;
    color: {TEXT_PRIMARY} !important;
    letter-spacing: 0.06em !important;
    overflow: visible !important;
    line-height: 1.3 !important;
    padding-top: 2px !important;
}}
h2, h3, h4, h5, h6 {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 500 !important;
    font-style: normal !important;
    text-transform: uppercase !important;
    color: {TEXT_PRIMARY} !important;
    letter-spacing: 0.06em !important;
    overflow: visible !important;
    line-height: 1.3 !important;
    padding-top: 2px !important;
}}
h1 {{ font-size: 1.75rem !important; }}
h2 {{ font-size: 1.15rem !important; }}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {{
    background: {BG_SURFACE} !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
    transition: none !important;
}}
section[data-testid="stSidebar"] > div {{
    transition: none !important;
}}
/* Logo area at top of sidebar */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div:first-child {{
    padding-top: 0 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    position: relative !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] svg {{
    display: none !important;
    pointer-events: none !important;
}}
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] * {{
    transition: none !important;
}}
/* Nav links — font and active state only, no wildcard * rule */
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: {TEXT_SECONDARY} !important;
    transition: none !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover span {{
    color: {ACCENT} !important;
}}
section[data-testid="stSidebar"] [aria-current="page"] span {{
    color: {ACCENT} !important;
}}
section[data-testid="stSidebar"] [aria-current="page"] {{
    background: {BG_HIGH} !important;
    border-right: 3px solid {ACCENT} !important;
}}


/* ── Inputs ── */
[data-baseweb="input"] {{
    background: {BG_HIGHEST} !important;
    border: none !important;
    border-bottom: 2px solid {BG_BORDER} !important;
    border-radius: 2px !important;
    transition: border-color 0.2s ease !important;
}}
[data-baseweb="input"]:focus-within {{
    border-bottom-color: {ACCENT} !important;
}}
[data-baseweb="input"] input {{
    background: transparent !important;
    color: {TEXT_PRIMARY} !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 400 !important;
    font-style: italic !important;
    font-size: 14px !important;
    border: none !important;
    outline: none !important;
}}
input, textarea {{
    background: {BG_HIGHEST} !important;
    border: none !important;
    border-bottom: 2px solid {BG_BORDER} !important;
    border-radius: 2px !important;
    color: {TEXT_PRIMARY} !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 400 !important;
    font-style: italic !important;
    font-size: 14px !important;
}}
input:focus, textarea:focus {{
    border-bottom-color: {ACCENT} !important;
    box-shadow: none !important;
    outline: none !important;
}}

/* ── Buttons — compact, no wrap ── */
.stButton > button {{
    background: linear-gradient(135deg, #f6ffc0 0%, {ACCENT} 100%) !important;
    color: #0e0e0e !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 500 !important;
    font-style: italic !important;
    font-size: 11px !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: 2px !important;
    padding: 0.45rem 1rem !important;
    white-space: nowrap !important;
    transition: all 0.15s ease !important;
    line-height: 1.4 !important;
}}
.stButton > button:hover {{
    box-shadow: 0 0 24px rgba(223,255,0,0.35) !important;
    filter: brightness(1.05) !important;
}}
.stButton > button:active {{
    transform: scale(0.97) !important;
}}

/* ── Checkbox ── */
[data-testid="stCheckbox"] {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    letter-spacing: 0.03em !important;
    color: {TEXT_SECONDARY} !important;
}}

/* ── Select / Multiselect ── */
/* ── Select / Multiselect container ── */
/* Root control — must stay full width in both focused and blurred states */
[data-baseweb="select"] {{
    width: 100% !important;
}}
[data-baseweb="select"] > div {{
    background: {BG_HIGHEST} !important;
    border: none !important;
    border-bottom: 2px solid {BG_BORDER} !important;
    border-radius: 2px !important;
    color: {TEXT_PRIMARY} !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-size: 13px !important;
    width: 100% !important;
    min-width: 0 !important;
    overflow: visible !important;
    box-sizing: border-box !important;
}}
/* Inner value container — the flex row holding tags + invisible input */
[data-baseweb="select"] > div > div:first-child {{
    overflow: visible !important;
    flex-wrap: wrap !important;
    width: 100% !important;
    min-width: 0 !important;
    padding-left: 6px !important;
    box-sizing: border-box !important;
}}
/* The live-search input sits inline with the tags.
   Hide it visually when the select is not focused — it reappears on click. */
[data-baseweb="select"] input {{
    width: 1px !important;
    min-width: 1px !important;
    max-width: 1px !important;
    flex-shrink: 1 !important;
    flex-grow: 0 !important;
    opacity: 0 !important;
    background: transparent !important;
    border: none !important;
    outline: none !important;
    padding: 0 !important;
    margin: 0 !important;
}}
[data-baseweb="select"]:focus-within input {{
    width: auto !important;
    min-width: 2px !important;
    max-width: none !important;
    opacity: 1 !important;
}}
/* Tags themselves */
[data-baseweb="tag"] {{
    background: {ACCENT_GLOW} !important;
    color: {ACCENT} !important;
    border: 1px solid {ACCENT_DIM} !important;
    border-radius: 2px !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-size: 10px !important;
    font-weight: 500 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    max-width: none !important;
    flex-shrink: 0 !important;
}}
/* Every element inside a tag — prevent any internal clipping */
[data-baseweb="tag"] * {{
    max-width: none !important;
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
}}

/* ── Number input ── */
[data-testid="stNumberInput"] input {{
    background: {BG_HIGHEST} !important;
    border: none !important;
    border-bottom: 2px solid {BG_BORDER} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0 !important;
    border-bottom: 1px solid {BG_BORDER} !important;
    background: transparent !important;
}}
.stTabs [data-baseweb="tab"] {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 500 !important;
    font-size: 10px !important;
    letter-spacing: 0.18em !important;
    color: {TEXT_MUTED} !important;
    padding: 10px 18px !important;
    border-radius: 0 !important;
    background: transparent !important;
    text-transform: uppercase !important;
    border-bottom: 2px solid transparent !important;
    white-space: nowrap !important;
    overflow: visible !important;
    transition: all 0.15s ease !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {TEXT_PRIMARY} !important;
    background: {BG_HIGH} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {ACCENT} !important;
    background: {ACCENT_SOFT} !important;
    border-bottom: 2px solid {ACCENT} !important;
}}

/* ── Expander ── */
[data-testid="stExpander"] {{
    background: {BG_SURFACE} !important;
    border: 1px solid {BG_BORDER} !important;
    border-radius: 2px !important;
}}
[data-testid="stExpander"] summary {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 400 !important;
    font-size: 10px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: {TEXT_SECONDARY} !important;
    overflow: visible !important;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{
    background: {BG_SURFACE} !important;
    border-radius: 2px !important;
    border: 1px solid {BG_BORDER} !important;
}}

/* ── Caption / small text ── */
.stCaption, [data-testid="stCaptionContainer"] p {{
    color: {TEXT_MUTED} !important;
    font-size: 10px !important;
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 300 !important;
    letter-spacing: 0.04em !important;
}}

/* ── Widget labels (Video file, Match data CSV, etc.) ── */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 400 !important;
    font-style: normal !important;
    font-size: 12px !important;
    color: {TEXT_SECONDARY} !important;
    letter-spacing: 0.03em !important;
}}

/* ── Body / paragraph text ── */
p, .stMarkdown p, [data-testid="stMarkdownContainer"] p {{
    font-family: 'Iosevka Charon Mono', monospace !important;
    font-weight: 300 !important;
    font-size: 13px !important;
}}

/* ── Warnings / info ── */
.stAlert {{
    border-radius: 2px !important;
    border-left-width: 3px !important;
    background: {BG_SURFACE} !important;
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: {BG_BASE}; }}
::-webkit-scrollbar-thumb {{ background: {BG_HIGHEST}; border-radius: 10px; }}
::-webkit-scrollbar-thumb:hover {{ background: {BG_BORDER}; }}

/* ════════════════════════════════
   COMPONENT CLASSES
════════════════════════════════ */

.cm-step-header {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 32px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid {BG_BORDER};
}}
.cm-step-num {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px; height: 24px;
    background: {ACCENT};
    border-radius: 2px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 11px; font-weight: 700;
    color: #0e0e0e;
    flex-shrink: 0;
    box-shadow: 0 0 12px rgba(223,255,0,0.4);
    letter-spacing: 0;
}}
.cm-step-label {{
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 10px; font-weight: 400;
    color: {ACCENT};
    letter-spacing: 0.22em;
    text-transform: uppercase;
    overflow: visible;
}}

.cm-log-box {{
    background: {BG_HIGHEST};
    color: {ACCENT};
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 11px;
    padding: 14px 16px;
    border-radius: 2px;
    height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    border: 1px solid {BG_BORDER};
    margin-top: 10px;
    line-height: 1.8;
}}

.cm-status-ready {{
    display: flex; align-items: center; gap: 12px;
    background: {ACCENT_GLOW};
    border: none;
    border-left: 3px solid {ACCENT};
    border-radius: 2px;
    padding: 14px 18px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {ACCENT};
    margin-bottom: 20px;
    overflow: visible;
}}
.cm-status-empty {{
    display: flex; align-items: center; gap: 12px;
    background: {BG_SURFACE};
    border: none;
    border-left: 3px solid {BG_BORDER};
    border-radius: 2px;
    padding: 14px 18px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {TEXT_MUTED};
    margin-bottom: 20px;
    overflow: visible;
}}

.cm-context-bar {{
    display: flex; gap: 28px; align-items: center;
    background: {BG_SURFACE};
    border: 1px solid {BG_BORDER};
    border-radius: 2px;
    padding: 10px 18px;
    font-size: 10px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {TEXT_SECONDARY};
    margin-bottom: 20px;
    flex-wrap: wrap;
    overflow: visible;
}}
.cm-ctx-item {{ display: flex; align-items: center; gap: 8px; }}
.cm-ctx-dot-ok  {{ width: 6px; height: 6px; border-radius: 50%; background: {ACCENT}; box-shadow: 0 0 6px {ACCENT}; flex-shrink:0; }}
.cm-ctx-dot-bad {{ width: 6px; height: 6px; border-radius: 50%; background: {RED}; box-shadow: 0 0 6px {RED}; flex-shrink:0; }}
.cm-ctx-dot-dim {{ width: 6px; height: 6px; border-radius: 50%; background: {BG_BORDER}; flex-shrink:0; }}

.cm-stats-bar {{
    display: flex; align-items: stretch;
    background: {BG_SURFACE};
    border-radius: 2px; overflow: hidden;
    border: 1px solid {BG_BORDER};
    margin-bottom: 20px;
}}
.cm-stats-cell {{
    flex: 1; padding: 16px 20px;
    text-align: center;
    border-right: 1px solid {BG_BORDER};
}}
.cm-stats-cell:last-child {{ border-right: none; }}
.cm-stats-label {{
    font-size: 9px; color: {TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: .18em;
    margin-bottom: 8px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 500;
    overflow: visible;
}}
.cm-stats-split {{ display: flex; justify-content: center; gap: 14px; margin-top: 4px; }}
.cm-stats-home  {{ color: {HOME_HEX}; font-size: 18px; font-weight: 400; font-family: 'Iosevka Charon Mono', monospace; }}
.cm-stats-away  {{ color: {AWAY_HEX}; font-size: 18px; font-weight: 400; font-family: 'Iosevka Charon Mono', monospace; }}

.cm-shot-panel, .cm-event-panel {{
    background: {BG_SURFACE};
    border: 1px solid {BG_BORDER};
    border-radius: 2px;
    border-left: 3px solid transparent;
    padding: 20px;
    transition: border-left-color 0.2s ease;
}}
.cm-shot-panel:hover, .cm-event-panel:hover {{
    border-left-color: {ACCENT};
}}
.cm-panel-title {{
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 13px; font-weight: 500;
    color: {TEXT_PRIMARY};
    margin-bottom: 4px;
    letter-spacing: -0.2px;
    overflow: visible;
}}
.cm-panel-sub {{
    font-size: 10px; color: {TEXT_MUTED};
    margin-bottom: 14px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 300;
    letter-spacing: 0.04em;
}}
.cm-detail-label {{
    font-size: 9px; color: {TEXT_MUTED};
    text-transform: uppercase; letter-spacing: .12em;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 400;
}}
.cm-detail-value {{
    font-size: 13px; font-weight: 400;
    color: {TEXT_PRIMARY};
    font-family: 'Iosevka Charon Mono', monospace;
}}

.cm-badge {{
    display: inline-block; font-size: 9px; font-weight: 900;
    padding: 2px 8px; border-radius: 2px;
    letter-spacing: .1em; text-transform: uppercase;
    margin-bottom: 12px;
    font-family: 'Iosevka Charon Mono', monospace;
    overflow: visible;
}}
.cm-badge-goal     {{ background: {ACCENT_GLOW}; color: {ACCENT}; border: 1px solid {ACCENT}; }}
.cm-badge-saved    {{ background: rgba(122,180,255,0.1); color: {BLUE}; border: 1px solid {BLUE}; }}
.cm-badge-missed   {{ background: {BG_HIGHEST}; color: {TEXT_MUTED}; border: 1px solid {BG_BORDER}; }}
.cm-badge-post     {{ background: rgba(200,130,255,0.1); color: #c882ff; border: 1px solid #c882ff; }}
.cm-badge-blocked  {{ background: {BG_HIGHEST}; color: {TEXT_SECONDARY}; border: 1px solid {BG_BORDER}; }}
.cm-badge-success  {{ background: {ACCENT_GLOW}; color: {ACCENT}; border: 1px solid {ACCENT_DIM}; }}
.cm-badge-fail     {{ background: rgba(255,115,81,0.1); color: {RED}; border: 1px solid {RED}; }}
.cm-badge-tackle   {{ background: rgba(122,180,255,0.1); color: {BLUE}; border: 1px solid {BLUE}; }}
.cm-badge-interc   {{ background: {ACCENT_GLOW}; color: {ACCENT}; border: 1px solid {ACCENT_DIM}; }}
.cm-badge-clear    {{ background: {BG_HIGHEST}; color: {TEXT_SECONDARY}; border: 1px solid {BG_BORDER}; }}
.cm-badge-aerial   {{ background: rgba(200,130,255,0.1); color: #c882ff; border: 1px solid #c882ff; }}
.cm-badge-block    {{ background: rgba(255,180,0,0.1); color: #ffb400; border: 1px solid #ffb400; }}
.cm-badge-challenge{{ background: rgba(0,220,200,0.1); color: #00dcc8; border: 1px solid #00dcc8; }}
.cm-badge-disp     {{ background: rgba(255,115,81,0.1); color: {RED}; border: 1px solid {RED}; }}
.cm-badge-no-data  {{ background: {BG_HIGHEST}; color: {TEXT_MUTED}; border: 1px solid {BG_BORDER}; }}

.cm-no-data-msg {{
    text-align: center; color: {TEXT_MUTED};
    padding: 60px 20px; font-size: 12px; line-height: 2.5;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 300;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}}

.cm-ai-box {{
    background: {BG_HIGHEST};
    color: {TEXT_PRIMARY};
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 13px; line-height: 1.8;
    padding: 18px 20px;
    border-radius: 2px;
    white-space: pre-wrap;
    border: 1px solid {BG_BORDER};
    margin-bottom: 12px;
}}

.cm-progress-label {{
    font-size: 9px; color: {TEXT_MUTED};
    margin-bottom: 5px;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}}

.cm-footer {{
    text-align: center;
    color: {TEXT_MUTED};
    font-size: 9px;
    padding-top: 28px;
    letter-spacing: 0.2em;
    font-family: 'Iosevka Charon Mono', monospace;
    font-weight: 300;
    text-transform: uppercase;
}}

.cm-support-footer {{
    margin-top: 32px;
    padding-top: 22px;
    border-top: 1px solid {BG_BORDER};
}}

.cm-support-panel {{
    background: {BG_SURFACE};
    border: 1px solid {BG_BORDER};
    border-radius: 4px;
    padding: 18px 20px;
    min-height: 100%;
}}

.cm-support-kicker {{
    color: {ACCENT};
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    font-family: 'Iosevka Charon Mono', monospace;
    margin-bottom: 8px;
}}

.cm-support-title {{
    color: {TEXT_PRIMARY};
    font-family: 'Iosevka Charon Mono', monospace;
    font-size: 1rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 8px;
}}

.cm-support-copy {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    line-height: 1.6;
    margin-bottom: 14px;
}}

.cm-support-meta {{
    color: {TEXT_MUTED};
    font-size: 10px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    font-family: 'Iosevka Charon Mono', monospace;
    margin-top: 14px;
}}

.cm-support-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 11px 18px;
    background: linear-gradient(180deg, #80b2ff 0%, #72a4f2 100%);
    color: #ffffff !important;
    border-radius: 12px;
    font-family: Inter, sans-serif;
    font-size: 15px;
    font-weight: 800;
    text-decoration: none !important;
    box-shadow: 0 10px 24px rgba(114,164,242,0.2);
}}

.cm-support-btn:hover {{
    filter: brightness(1.06);
}}

.cm-support-qr-wrap {{
    background: #ffffff;
    border-radius: 4px;
    padding: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    max-width: 220px;
    margin: 0 auto;
}}

.cm-support-qr-wrap img {{
    display: block;
    width: 100%;
    height: auto;
}}

.cm-support-qr-caption {{
    display: block;
    width: 100%;
    text-align: center;
    color: {TEXT_MUTED};
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-family: 'Iosevka Charon Mono', monospace;
    margin-top: 10px;
}}
</style>
"""


_CSS_CACHE = {}
_LIGHT_QUERY_PARAM = "cm_light"
_LIGHT_STORAGE_KEY = "clipmaker_light_mode"
_THEME_PREF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".clipmaker_theme")


def _read_query_light_value():
    import streamlit as st

    try:
        raw = st.query_params.get(_LIGHT_QUERY_PARAM)
    except Exception:
        try:
            raw = st.experimental_get_query_params().get(_LIGHT_QUERY_PARAM)
        except Exception:
            return None

    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None

    raw = str(raw).strip().lower()
    if raw in {"1", "true", "yes", "on", "light"}:
        return True
    if raw in {"0", "false", "no", "off", "dark"}:
        return False
    return None


def _set_query_light_value(light: bool):
    import streamlit as st

    value = "1" if light else "0"
    try:
        if st.query_params.get(_LIGHT_QUERY_PARAM) != value:
            st.query_params[_LIGHT_QUERY_PARAM] = value
    except Exception:
        try:
            st.experimental_set_query_params(**{_LIGHT_QUERY_PARAM: value})
        except Exception:
            pass


def _read_persisted_light_mode():
    try:
        with open(_THEME_PREF_PATH, "r", encoding="utf-8") as f:
            raw = f.read().strip().lower()
    except Exception:
        return None

    if raw in {"1", "true", "yes", "on", "light"}:
        return True
    if raw in {"0", "false", "no", "off", "dark"}:
        return False
    return None


def _write_persisted_light_mode(light: bool):
    try:
        with open(_THEME_PREF_PATH, "w", encoding="utf-8") as f:
            f.write("1" if light else "0")
    except Exception:
        pass


def _sync_light_mode_from_query():
    import streamlit as st

    if "light_mode" in st.session_state:
        return

    query_light = _read_query_light_value()
    if query_light is None:
        persisted_light = _read_persisted_light_mode()
        st.session_state["light_mode"] = bool(persisted_light) if persisted_light is not None else False
        return

    st.session_state["light_mode"] = query_light
    _write_persisted_light_mode(query_light)

def _build_css(light: bool = False) -> str:
    key = "light" if light else "dark"
    if key not in _CSS_CACHE:
        # Always start from the dark base (which has correct font injection).
        # For light mode we append a comprehensive override block rather than
        # doing fragile string-replacement (which breaks when the same hex value
        # appears in multiple semantic roles, e.g. #0e0e0e as background AND
        # as button-text colour).
        css = GLOBAL_CSS.replace(
            "/* fonts injected dynamically by inject() */",
            _fonts_import(),
            1,
        )
        if light:
            css = css + LIGHT_MODE_CSS
        _CSS_CACHE[key] = css
    return _CSS_CACHE[key]


@_functools.lru_cache(maxsize=4)
def _cached_css(light: bool) -> str:
    return _build_css(light=light)


def _sidebar_branding_css(logo_b64: str = "", first_nav_label: str = "") -> str:
    brand_block = ""
    if logo_b64:
        brand_block = f"""
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::before {{
    content: "";
    position: absolute;
    top: 16px;
    left: 16px;
    right: 16px;
    height: 52px;
    background: url("data:image/png;base64,{logo_b64}") center center / 52px 52px no-repeat;
    pointer-events: none;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::after {{
    content: "CLIPMAKER\\A v1.2.3 · B4L1";
    white-space: pre;
    position: absolute;
    top: 74px;
    left: 16px;
    right: 16px;
    text-align: center;
    font-family: 'Inter', sans-serif !important;
    font-size: 9px;
    font-weight: 900;
    line-height: 1.9;
    letter-spacing: 0.25em;
    color: {ACCENT};
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    text-shadow: 0 0 12px rgba(223,255,0,0.18);
    pointer-events: none;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {{
    margin-top: 132px !important;
}}
"""
    return f"<style>{brand_block}</style>"


def inject(logo_path: str = "", first_nav_label: str = ""):
    import streamlit as st
    import streamlit.components.v1 as _cv1

    _sync_light_mode_from_query()
    light = st.session_state.get("light_mode", False)
    st.markdown(_cached_css(light), unsafe_allow_html=True)
    # Sidebar branding is intentionally disabled in navbar mode.

    # Runtime guardrails for Streamlit DOM mutations:
    # keep select tags from clipping without forcing sidebar state/width.
    # Must use components.html — st.markdown strips <script> tags.
    _sel = '[data-baseweb="tag"]'
    _js = (
        "<script>(function(){"
        "var w=window.parent||window;"
        "var d=w.document||document;"
        "var storageKey='" + _LIGHT_STORAGE_KEY + "';"
        "var queryKey='" + _LIGHT_QUERY_PARAM + "';"
        "try{"
        "var stored=w.localStorage&&w.localStorage.getItem(storageKey);"
        "var url=new URL(w.location.href);"
        "var current=url.searchParams.get(queryKey);"
        "if((stored==='1'||stored==='0')&&(current===null||current==='')){"
        "url.searchParams.set(queryKey,stored);"
        "w.location.replace(url.toString());"
        "return;"
        "}"
        "}catch(e){}"
        "var sel='" + _sel + "';"
        "var qs=new URLSearchParams(w.location.search);"
        "var safeSidebar=qs.get('safeSidebar')==='1';"
        "if(safeSidebar){"
        "var st=d.createElement('style');"
        "st.textContent='"
        "section[data-testid=\"stSidebar\"] [data-testid=\"stSidebarContent\"]::before,"
        "section[data-testid=\"stSidebar\"] [data-testid=\"stSidebarContent\"]::after{content:none!important;}"
        "section[data-testid=\"stSidebar\"] [data-testid=\"stSidebarNav\"]{margin-top:0!important;}"
        "section[data-testid=\"stSidebar\"] [data-testid=\"stSidebarNavLink\"] svg{display:inline-block!important;}"
        "';"
        "d.head.appendChild(st);"
        "return;"
        "}"
        "function fixTags(){"
        "d.querySelectorAll(sel).forEach(function(t){"
        "t.style.setProperty('max-width','none','important');"
        "t.style.setProperty('overflow','visible','important');"
        "t.querySelectorAll('*').forEach(function(c){"
        "c.style.setProperty('max-width','none','important');"
        "c.style.setProperty('overflow','visible','important');"
        "c.style.setProperty('text-overflow','unset','important');"
        "c.style.setProperty('white-space','nowrap','important');"
        "});});}"
        "function stabilize(){fixTags();}"
        "stabilize();setTimeout(stabilize,250);setTimeout(stabilize,800);setTimeout(stabilize,1600);"
        "var runs=0,maxRuns=8;"
        "var iv=setInterval(function(){stabilize();runs+=1;if(runs>=maxRuns){clearInterval(iv);}},220);"
        "w.addEventListener('resize',stabilize,{passive:true});"
        "w.addEventListener('popstate',stabilize,{passive:true});"
        "d.addEventListener('visibilitychange',function(){if(!d.hidden){stabilize();}},{passive:true});"
        "})();</script>"
    )
    _cv1.html(_js, height=0, scrolling=False)


def light_color(dark_val: str, light_val: str) -> str:
    """Return the appropriate color for the current theme.
    Call from any page to get theme-aware inline colours."""
    import streamlit as st
    return light_val if st.session_state.get("light_mode", False) else dark_val


SHARED_STATE_DEFAULTS = {
    "video_path": "",
    "video2_path": "",
    "video3_path": "",
    "video4_path": "",
    "video5_path": "",
    "csv_path": "",
    "output_dir": "",
    "half1_time": "",
    "half2_time": "",
    "half3_time": "",
    "half4_time": "",
    "half5_time": "",
    "had_extra_time": False,
    "had_penalties": False,
    "split_video": False,
    "split_extra_time_video": False,
    "extra_time_video_mode": "single",
    "split_penalties_video": False,
    "whoscored_url": "",
        "before_buffer": 5,
        "after_buffer": 8,
    "min_gap": 6,
    "scraped_csv_path": "",
    "scraped_csv_df": "",
    "scraper_home_team": "",
    "scraper_away_team": "",
}


def init_shared_state():
    import streamlit as st

    _sync_light_mode_from_query()

    for key, default in SHARED_STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default

    scraped_csv = st.session_state.get("scraped_csv_path", "")
    if scraped_csv and not st.session_state.get("csv_path"):
        st.session_state["csv_path"] = scraped_csv


def render_top_nav(current_page: str = ""):
    import streamlit as st
    import streamlit.components.v1 as _cv1

    items = [
        ("home", "ClipMaker.py", "Home", "[SETUP]"),
        ("filtering", "pages/1_Filtering_Output.py", "Filtering", "[FILTER]"),
        ("analyst", "pages/2_The_Analysts_Room.py", "Analyst's Room", "[RESULT]"),
        ("tactical", "pages/3_Tactical_Lab.py", "Tactical Lab", "[DATA]"),
    ]

    cols = st.columns([1.35, 1.75, 2.85, 2.25, 3.75, 2.0], gap="small")
    light_mode = st.session_state.get("light_mode", False)
    for col, (page_key, page_path, label, token) in zip(cols[:len(items)], items):
        with col:
            nav_label = f"{label} ·" if page_key == current_page else label
            st.page_link(page_path, label=nav_label, icon=icon_shortcode(token))

    with cols[4]:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        prev = st.session_state.get("light_mode", False)
        light_mode = st.toggle("☀ Light", key="light_mode", help="Toggle light/dark theme")
        if light_mode != prev:
            _set_query_light_value(light_mode)
            _write_persisted_light_mode(light_mode)
            _CSS_CACHE.clear()
            _cached_css.cache_clear()
            st.rerun()
        _set_query_light_value(light_mode)
        _write_persisted_light_mode(light_mode)

        _cv1.html(
            (
                "<script>(function(){"
                "var w=window.parent||window;"
                "try{"
                "var value='" + ("1" if light_mode else "0") + "';"
                "var queryKey='" + _LIGHT_QUERY_PARAM + "';"
                "w.localStorage&&w.localStorage.setItem('" + _LIGHT_STORAGE_KEY + "',value);"
                "var url=new URL(w.location.href);"
                "if(url.searchParams.get(queryKey)!==value){"
                "url.searchParams.set(queryKey,value);"
                "w.history.replaceState({},'',url.toString());"
                "}"
                "function syncThemeLinks(){"
                "var links=w.document.querySelectorAll('[data-testid=\"stPageLink\"] a,a[href*=\"ClipMaker.py\"],a[href*=\"1_Filtering_Output.py\"],a[href*=\"2_The_Analysts_Room.py\"],a[href*=\"3_Tactical_Lab.py\"]');"
                "links.forEach(function(a){"
                "try{var u=new URL(a.getAttribute('href'),w.location.href);u.searchParams.set(queryKey,value);a.setAttribute('href',u.pathname+u.search+u.hash);}catch(e){}"
                "});"
                "}"
                "syncThemeLinks();setTimeout(syncThemeLinks,100);setTimeout(syncThemeLinks,400);setTimeout(syncThemeLinks,1000);"
                "var mo=new MutationObserver(syncThemeLinks);"
                "mo.observe(w.document.body,{childList:true,subtree:true});"
                "}catch(e){}"
                "})();</script>"
            ),
            height=0,
            scrolling=False,
        )

    st.markdown('<div class="cm-topnav-divider"></div>', unsafe_allow_html=True)


def render_support_footer(page_label: str = ""):
    import streamlit as st
    from urllib.parse import quote

    kofi_url = "https://ko-fi.com/R6R71WP4PR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(kofi_url, safe='')}"
    meta = "@B03GHB4L1" if not page_label else f"@B03GHB4L1 · {page_label}"

    st.markdown('<div class="cm-support-footer"></div>', unsafe_allow_html=True)
    qr_col, info_col = st.columns([1.1, 2.0], gap="medium")

    with qr_col:
        st.markdown(
            f"""
            <div class="cm-support-qr-wrap">
              <img src="{qr_url}" alt="Ko-fi QR code"/>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with info_col:
        st.markdown(
            f"""
            <div class="cm-support-panel">
              <div class="cm-support-kicker">Support ClipMaker</div>
              <div class="cm-support-title">Enjoying the app?</div>
              <div class="cm-support-copy">
                If ClipMaker saves you time or helps your workflow, you can support future updates,
                maintenance, and new features on Ko-fi.
              </div>
              <a class="cm-support-btn" href="{kofi_url}" target="_blank" rel="noopener noreferrer">
                Support me on Ko-fi
              </a>
              <div class="cm-support-meta">{meta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


import functools as _functools

@_functools.lru_cache(maxsize=4)
def _cached_css(light: bool) -> str:
    return _build_css(light=light)

@_functools.lru_cache(maxsize=8)
def load_logo_b64(path: str) -> str:
    """Read and base64-encode a logo file, cached by path."""
    try:
        with open(path, "rb") as f:
            return __import__("base64").b64encode(f.read()).decode()
    except Exception:
        return ""

def step_header(num: int, label: str) -> str:
    return (
        f'<div class="cm-step-header">'
        f'<span class="cm-step-num">{num}</span>'
        f'<span class="cm-step-label">{label}</span>'
        f'</div>'
    )


def logo_header(title: str, subtitle: str, logo_b64: str = None, uppercase_title: bool = True) -> str:
    # No border-radius or background box — logo stands alone against the page bg
    if logo_b64:
        img = (
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'style="width:46px;height:46px;object-fit:contain;background:none;'
            f'filter:drop-shadow(0 0 10px rgba(223,255,0,0.25))"/>' 
        )
    else:
        img = '<span style="font-size:18px;font-family:Inter,sans-serif;font-weight:800;letter-spacing:.12em;color:var(--cm-title,#111111)">CM</span>'
    title_transform = "none" if not uppercase_title else "uppercase"
    return (
        f"<div style='display:flex;align-items:center;gap:16px;margin-bottom:10px;overflow:visible'>"
        f"  {img}"
        f"  <div style='overflow:visible;padding-top:4px'>"
        f"    <div style='font-family:\"Iosevka Charon Mono\",monospace;font-size:1.75rem;font-weight:700;"
        f"                color:var(--cm-title,#111111);letter-spacing:0.06em;line-height:1.3;"
        f"                text-transform:{title_transform};"
        f"                overflow:visible;white-space:nowrap'>{title}</div>"
        f"    <div style='color:var(--cm-subtitle,#767575);font-size:9px;margin-top:4px;"
        f"                font-family:Inter,sans-serif;font-weight:700;"
        f"                letter-spacing:0.2em;text-transform:uppercase'>{subtitle}</div>"
        f"  </div>"
        f"</div>"
        f"<div style='height:1px;background:linear-gradient(90deg,rgba(223,255,0,0.6),transparent);"
        f"            margin-bottom:20px'></div>"
    )


def sidebar_logo(logo_b64: str) -> str:
    """Inject logo at top of sidebar using st.sidebar.markdown."""
    return (
        f"<div style='padding:20px 16px 8px 16px;text-align:center'>"
        f"  <img src='data:image/png;base64,{logo_b64}' "
        f"    style='width:52px;height:52px;object-fit:contain;background:none;"
        f"    filter:drop-shadow(0 0 12px rgba(223,255,0,0.3))'/>"
        f"  <div style='font-family:Inter,sans-serif;font-size:9px;font-weight:900;"
        f"              color:#DFFF00;letter-spacing:0.25em;text-transform:uppercase;"
        f"              margin-top:8px'>ClipMaker</div>"
        f"  <div style='font-size:8px;color:#484847;font-weight:700;"
        f"              letter-spacing:0.15em;text-transform:uppercase;margin-top:2px'>v1.2 · B4L1</div>"
        f"</div>"
        f"<div style='height:1px;background:rgba(255,255,255,0.05);margin:0 16px 8px'></div>"
    )


def status_ready(filename: str) -> str:
    return (
        f'<div class="cm-status-ready">'
        f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;'
        f'background:#DFFF00;box-shadow:0 0 8px #DFFF00;flex-shrink:0"></span>'
        f'&nbsp;<strong>{filename}</strong>&nbsp;loaded — head to '
        f'<strong>Filtering</strong> to build your reel'
        f'</div>'
    )


def status_empty() -> str:
    return (
        '<div class="cm-status-empty">'
        '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;'
        'background:#2c2c2c;flex-shrink:0"></span>'
        '&nbsp;Start by scraping a match below, or load your files manually in Steps 1–2'
        '</div>'
    )


def context_bar(csv_ok, video_ok, times_ok, csv_name, video_name, times_str,
                before_buf, after_buf, min_gap) -> str:
    def dot(ok):
        cls = "ok" if ok else "bad"
        return f'<span class="cm-ctx-dot-{cls}"></span>'
    def dot_dim():
        return '<span class="cm-ctx-dot-dim"></span>'
    return (
        f'<div class="cm-context-bar">'
        f'<div class="cm-ctx-item">{dot(csv_ok)} <span>{csv_name}</span></div>'
        f'<div class="cm-ctx-item">{dot(video_ok)} <span>{video_name}</span></div>'
        f'<div class="cm-ctx-item">{dot(times_ok)} <span>Kick-offs: {times_str}</span></div>'
        f'<div class="cm-ctx-item">{dot_dim()} <span>Buffer {before_buf}s · {after_buf}s · {min_gap}s merge</span></div>'
        f'</div>'
    )


def icon_name(token: str) -> str:
    t = (token or "").strip().upper()
    if not t.startswith("["):
        t = f"[{t}]"
    return ICON_MAP.get(t, "radio_button_unchecked")


def icon_shortcode(token: str) -> str:
    return f":material/{icon_name(token)}:"


def icon_glyph(token: str) -> str:
    t = (token or "").strip().upper()
    if not t.startswith("["):
        t = f"[{t}]"
    return ICON_GLYPH_MAP.get(t, "•")


def icon_span(token: str, color: str = "", size: int = 14) -> str:
    style = [f"font-size:{int(size)}px", "line-height:1", "display:inline-flex", "align-items:center"]
    if color:
        style.append(f"color:{color}")
    else:
        style.append("color:var(--cm-icon, currentColor)")
    return (
        f"<span class='cm-icon' aria-hidden='true' style='{' ; '.join(style)}'>"
        f"{icon_glyph(token)}"
        "</span>"
    )


def ui(text: str) -> str:
    if not text:
        return text
    return _ICON_TOKEN_PATTERN.sub(lambda m: icon_shortcode(f"[{m.group(1)}]"), text)


def ui_html(text: str, color: str = "", size: int = 14) -> str:
    if not text:
        return text
    return _ICON_TOKEN_PATTERN.sub(lambda m: icon_span(f"[{m.group(1)}]", color=color, size=size), text)
