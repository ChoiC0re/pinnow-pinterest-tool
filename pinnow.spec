# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')
bs4_datas, _, bs4_hidden = collect_all('bs4')

a = Analysis(
    ['pinnow_app.py'],
    pathex=[],
    binaries=playwright_binaries,
    datas=[
        ('pinnow.py', '.'),
        ('fonts/FlorDeRuina-Germen.otf', 'fonts'),
        ('fonts/FlorDeRuina-Semilla.otf', 'fonts'),
        ('fonts/Pretendard-Light.otf', 'fonts'),
        ('fonts/Pretendard-Regular.otf', 'fonts'),
        ('fonts/Pretendard-Bold.otf', 'fonts'),
        ('assets/silver-pin.png', 'assets'),
        *playwright_datas,
        *bs4_datas,
    ],
    hiddenimports=[
        *playwright_hiddenimports,
        *bs4_hidden,
        'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui',
        'requests', 'tqdm', 'click', 'bs4', 'browser_cookie3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

icon_file = 'pinnow.ico' if sys.platform == 'win32' else 'pinnow.icns'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pinnow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='pinnow',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='pinnow.app',
        icon='pinnow.icns',
        bundle_identifier='com.pinnow.app',
        info_plist={
            'CFBundleName': 'pinnow',
            'CFBundleDisplayName': 'pinnow',
            'NSHighResolutionCapable': True,
            'LSMultipleInstancesProhibited': True,
            'LSMinimumSystemVersion': '11.0',
            'CFBundleShortVersionString': '1.1.0',
        },
    )
