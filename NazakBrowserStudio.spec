# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Root directory of the repository
ROOT_DIR = os.path.abspath(SPECPATH)

# Data assets and web assets
datas = [
    (os.path.join(ROOT_DIR, 'nazak', 'web'), 'nazak/web'),
    (os.path.join(ROOT_DIR, 'data', 'assets'), 'data/assets'),
]

binaries = []
hiddenimports = [
    'psutil',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'qfluentwidgets',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'websockets.legacy',
    'websockets.legacy.server',
    'socks',
]

# Automated collection of third-party dependencies
core_packages = [
    'uvicorn',
    'fastapi',
    'pydantic',
    'pydantic_core',
    'rich',
    'httpx',
    'socks',
    'playwright',
    'qfluentwidgets',
    'PyQt6'
]

for pkg in core_packages:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Exclude unnecessary heavy components and unused Qt6 modules to optimize footprint
excludes = [
    # Machine learning / Data science bloat
    'torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorboard',
    'keras', 'paddle', 'onnxruntime', 'scipy', 'sklearn', 'scikit_learn',
    'bitsandbytes', 'llvmlite', 'numba', 'matplotlib', 'pandas', 'pyarrow',
    'IPython', 'notebook', 'sympy', 'transformers', 'accelerate', 'cuda',
    # Unused Qt6 modules
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtPdf',
    'PyQt6.QtPdfWidgets',
    'PyQt6.Qt3DCore',
    'PyQt6.Qt3DRender',
    'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic',
    'PyQt6.Qt3DAnimation',
    'PyQt6.Qt3DExtras',
    'PyQt6.QtBluetooth',
    'PyQt6.QtNfc',
    'PyQt6.QtSensors',
    'PyQt6.QtSpatialAudio',
    'PyQt6.QtDesigner',
    'PyQt6.QtTest',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtPositioning',
    'PyQt6.QtLocation',
    # Unused standard libraries & test frameworks
    'tkinter',
    'unittest',
    'test',
]

a = Analysis(
    ['nazak/main.py'],
    pathex=[ROOT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=1,  # Bytecode optimization (strips assert statements)
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NazakBrowserStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Set to False to avoid antivirus heuristic false-positives
    console=False,  # Pure GUI Window without flashing console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'data', 'assets', 'icon.ico'),
    version=os.path.join(ROOT_DIR, 'version_info.txt'),
    manifest=os.path.join(ROOT_DIR, 'app.manifest'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NazakBrowserStudio',
)
