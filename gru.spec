# vim: set ft=python:
"""PyInstaller spec: bundles gru-nicegui into a single standalone executable.

NiceGUI's own static assets (JS/CSS/templates) are collected automatically by
pyinstaller-hooks-contrib's hook-nicegui.py -- only our own package data needs listing here.
"""

datas = [
    ('gru_ui/assets/gru.png', 'gru_ui/assets'),
    ('gru_ui/assets/icon.png', 'gru_ui/assets'),
    ('gru_ui/assets/icon.ico', 'gru_ui/assets'),
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # We use pywebview's GTK backend
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='gru',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon='gru_ui/assets/icon.ico',  # only embeds on Windows/macOS; PyInstaller ignores it on Linux
)
