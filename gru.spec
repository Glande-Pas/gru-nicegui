# vim: set ft=python:
"""PyInstaller spec: bundles gru-nicegui into a single standalone executable."""

import importlib.metadata
import pathlib
import os

console = os.environ.get('GRU_CONSOLE', '1') != '0'


build_versions = pathlib.Path(SPECPATH) / 'gru_ui' / '_build_version.py'  # noqa: F821 -- defined by PyInstaller
if not build_versions.exists():
    versions = {
        'gru-nicegui': importlib.metadata.version('gru-nicegui'),
        'gru': importlib.metadata.version('gru'),
    }
    with build_versions.open('w') as f:  # noqa: F821
        f.write(f'VERSIONS = {versions!r}\n')

    print('Detected versions:', versions)

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
    console=console,
    icon='gru_ui/assets/icon.ico',  # only embeds on Windows/macOS; PyInstaller ignores it on Linux
)
