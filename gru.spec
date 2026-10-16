# vim: set ft=python:
"""PyInstaller spec: bundles gru-nicegui into a single standalone executable (a .app bundle on macOS)."""

import importlib.metadata
import pathlib
import os
import sys

console = os.environ.get('GRU_CONSOLE', '1') != '0'


build_versions = pathlib.Path(SPECPATH) / 'gru_ui' / '_build_version.py'  # noqa: F821 -- defined by PyInstaller
if not build_versions.exists():
    versions = {
        'gru-nicegui': importlib.metadata.version('gru-nicegui'),
        'gru-eso': importlib.metadata.version('gru-eso'),
    }
    with build_versions.open('w') as f:  # noqa: F821
        f.write(f'VERSIONS = {versions!r}\n')

    print('Detected versions:', versions)

datas = [
    ('gru_ui/assets/gru.png', 'gru_ui/assets'),
    ('gru_ui/assets/icon.png', 'gru_ui/assets'),
    ('gru_ui/assets/icon.ico', 'gru_ui/assets'),
    ('gru_ui/assets/git.png', 'gru_ui/assets'),
    ('gru_ui/assets/local.png', 'gru_ui/assets'),
    ('gru_ui/assets/ambiguous.png', 'gru_ui/assets'),
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

exe_args = dict(name='gru', debug=False, bootloader_ignore_signals=False, strip=False, console=console)

if sys.platform == 'darwin':
    # A .app bundle can't be a onefile executable: onedir, collected then wrapped
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, upx=False, **exe_args)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='gru')
    app = BUNDLE(
        coll,
        name='Gru.app',
        icon='packaging/macos/icon.icns',
        bundle_identifier='io.github.Glande_Pas.Gru',
        version=importlib.metadata.version('gru-nicegui'),
        # TODO: add CFBundleURLTypes for the gru:// scheme to this plist (and handle the kAEGetURL Apple Event)
        info_plist={'CFBundleName': 'Gru', 'NSHighResolutionCapable': True},
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        icon='gru_ui/assets/icon.ico',  # only embeds on Windows; PyInstaller ignores it on Linux
        **exe_args,
    )
