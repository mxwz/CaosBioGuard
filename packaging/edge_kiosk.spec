# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：Kiosk 单目录打包（Windows / Linux 通用）。

用法（在项目根执行）：
    python -m PyInstaller packaging/edge_kiosk.spec --noconfirm --clean
产物：
    dist/CaosBioGuardKiosk/CaosBioGuardKiosk(.exe)
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

hiddenimports = (
    collect_submodules('sideUI.kiosk')
    + collect_submodules('ui_kit')
    + collect_submodules('biometrics')
    + ['version', 'managers', 'registry']
)

a = Analysis(
    [os.path.join(ROOT, 'packaging', 'kiosk_entry.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CaosBioGuardKiosk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    name='CaosBioGuardKiosk',
)
