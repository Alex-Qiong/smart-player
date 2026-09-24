# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows）：生成单文件夹版 SmartPlayer。

步骤：
    pip install -r requirements.txt pyinstaller
    python tools/fetch_libmpv.py
    pyinstaller player.spec
    # 产物在 dist/SmartPlayer/，首次运行再执行 tools/download_models.py --all
"""
import os
from pathlib import Path

block_cipher = None
ROOT = Path(os.path.abspath("."))

a = Analysis(
    [str(ROOT / "src" / "smartplayer" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=[
        # libmpv-2.dll（tools/fetch_libmpv.py 下载到项目根目录）
        (str(ROOT / "libmpv-2.dll"), "."),
    ],
    datas=[],
    hiddenimports=[
        "mpv",
        "faster_whisper",
        "ctranslate2",
        "argostranslate.translate",
        "argostranslate.package",
        "piper",
        "imageio_ffmpeg",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 程序不弹黑框；调试时可改为 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SmartPlayer",
)
