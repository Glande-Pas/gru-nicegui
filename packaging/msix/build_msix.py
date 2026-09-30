#!/usr/bin/env python3
# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Package the PyInstaller-built gru.exe as an unsigned MSIX for the Microsoft Store, which re-signs it.

Usage: build_msix.py EXE ARCH OUTPUT, e.g. build_msix.py dist/gru.exe x64 dist/gru-x64.msix
Needs the Windows SDK's makeappx.exe.
"""

import glob
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def package_version() -> str:
    """pyproject's version as MSIX wants it: four numbers, the last one 0 for Store submissions."""
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    parts = [int(part) for part in version.split('.')[:3]]
    return '.'.join(map(str, parts + [0] * (3 - len(parts)) + [0]))


def find_makeappx() -> str:
    """The newest makeappx.exe from the installed Windows SDKs, preferring the host architecture's."""
    kits = os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Windows Kits', '10', 'bin')
    host = 'arm64' if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'ARM64' else 'x64'
    for arch in dict.fromkeys([host, 'x64']):
        found = sorted(glob.glob(os.path.join(kits, '10.*', arch, 'makeappx.exe')),
                       key=lambda path: [int(n) for n in pathlib.Path(path).parent.parent.name.split('.')])
        if found:
            return found[-1]
    if shutil.which('makeappx'):
        return 'makeappx'
    sys.exit(f'makeappx.exe not found under {kits}: the Windows SDK is required')


def main(exe: str, arch: str, output: str) -> None:
    with tempfile.TemporaryDirectory() as staging_dir:
        staging = pathlib.Path(staging_dir)
        shutil.copy2(exe, staging / 'gru.exe')

        shutil.copytree(HERE / 'Assets', staging / 'Assets')

        manifest = (HERE / 'AppxManifest.xml').read_text(encoding='utf-8')
        manifest = manifest.replace('{VERSION}', package_version()).replace('{ARCH}', arch)
        (staging / 'AppxManifest.xml').write_text(manifest, encoding='utf-8')

        pathlib.Path(output).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([find_makeappx(), 'pack', '/d', str(staging), '/p', output, '/o'], check=True)
    print(f'Packaged {output} (version {package_version()}, {arch})')


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[2] not in {'x64', 'arm64'}:
        sys.exit(__doc__)
    main(*sys.argv[1:])
