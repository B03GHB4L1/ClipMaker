# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parents[1]

datas = [(str(ROOT / "app"), "app"), (str(ROOT / "ui"), "ui")]
binaries = []
hiddenimports = [
    "clipmaker_core",
    "scoresway_scraper",
    "whoscored_scraper",
    "theme",
    "team_names",
    "analysis_core",
    "analysis_core.frames",
    "analysis_core.registry",
    "analysis_core.common",
    "analysis_core.shot_map",
    "analysis_core.video",
    "analysis_core.views",
    "analysis_core.event_maps",
    "analysis_core.pressing",
    "analysis_core.build_up",
    "analysis_core.comparison",
    "analysis_core.comparison_helpers",
    "smp_component",
    "project_analysis",
    "analysis_server",
    "tkinter",
    "tkinter.filedialog",
]
for package in ("playwright", "imageio_ffmpeg", "streamlit"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "packaging" / "clipmaker_api_server.py")],
    pathex=[str(ROOT), str(ROOT / "app"), str(ROOT / "packaging")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "langchain",
        "lxml",
        "matplotlib",
        "nbformat",
        "notebook",
        "pytest",
        "scipy",
        "sklearn",
        "sympy",
        "tensorflow",
        "torch",
        "zmq",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="clipmaker-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="clipmaker-server",
)
