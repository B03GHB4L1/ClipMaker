# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parents[1]

datas = [(str(ROOT / "app"), "app")]
binaries = []
hiddenimports = [
    "clipmaker_core",
    "scoresway_scraper",
    "whoscored_scraper",
    "theme",
    "smp_component",
    "tkinter",
    "tkinter.filedialog",
]
hiddenimports += collect_submodules("streamlit.runtime.scriptrunner")

datas += collect_data_files("streamlit")
datas += copy_metadata("streamlit")

for package in ("playwright", "imageio_ffmpeg"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "packaging" / "clipmaker_server.py")],
    pathex=[str(ROOT), str(ROOT / "app")],
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
    console=False,
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
