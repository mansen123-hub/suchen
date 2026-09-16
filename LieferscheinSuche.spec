# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPEC).resolve().parent
ocr_dir = project / "build" / "vendor" / "ocr"
datas = []
if ocr_dir.exists():
    datas.append((str(ocr_dir), "ocr"))

hiddenimports = collect_submodules("watchdog.observers")

a = Analysis(
    [str(project / "run_app.py")],
    pathex=[str(project)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "pytest", "lxml", "openpyxl", "PIL"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LieferscheinSuche",
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
    icon=str(project / "build" / "app.ico"),
    version=str(project / "build" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LieferscheinSuche",
)
