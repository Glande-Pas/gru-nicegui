"""Pin gru and gru-nicegui's Python dependencies as flatpak-builder sources: python-deps.json.

Flatpak builds run offline, so every wheel is listed with its URL and checksum. Binary wheels are
resolved separately for each architecture and tagged with only-arches.

Usage: generate_python_deps.py GRU_PYPROJECT [PYTHON_VERSION]
"""

import json
import urllib.request
import pathlib
import subprocess
import sys
import tempfile
import tomllib

# The runtime's glibc is newer than all of these; pip doesn't infer older manylinux tags itself
MANYLINUX = ['manylinux_2_28', 'manylinux_2_17', 'manylinux2014']
ARCHES = ['x86_64', 'aarch64']
# Provided by the GNOME runtime
SKIP = {'pygobject', 'pycairo'}
# Published only as sdists, pure Python: built into wheels in the sandbox. Without them, pip silently
# resolves to old versions of whatever depends on them (pywebview 3.4).
SDISTS = ['proxy-tools']

HERE = pathlib.Path(__file__).parent


def requirements(gru_pyproject: pathlib.Path) -> list[str]:
    reqs = []
    for pyproject in (HERE.parent.parent / 'pyproject.toml', gru_pyproject):
        reqs += tomllib.loads(pyproject.read_text())['project']['dependencies']
    return sorted({req for req in reqs if req.lower() != 'gru'})


def sdist(name: str, version: str) -> dict:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json') as response:
        release = json.load(response)
    file, = (file for file in release['urls'] if file['packagetype'] == 'sdist')
    return {'type': 'file', 'url': file['url'], 'sha256': file['digests']['sha256']}


def resolve(reqs: list[str], arch: str, python: str, wheels: pathlib.Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        report = pathlib.Path(tmp) / 'report.json'
        subprocess.run([
            sys.executable, '-m', 'pip', 'install', '--quiet', '--dry-run', '--ignore-installed',
            '--only-binary=:all:', '--implementation=cp', f'--python-version={python}',
            *(f'--platform={tag}_{arch}' for tag in MANYLINUX), f'--report={report}', f'--find-links={wheels}', *reqs,
        ], check=True)
        return json.loads(report.read_text())['install']


def main(gru_pyproject: str, python: str = '3.13') -> None:
    reqs = requirements(pathlib.Path(gru_pyproject))
    sources: dict[str, dict] = {}
    versions: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as wheels:
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--quiet', '--no-deps', '--no-binary=:all:',
                        f'--wheel-dir={wheels}', *SDISTS], check=True)
        for arch in ARCHES:
            for item in resolve(reqs, arch, python, pathlib.Path(wheels)):
                name, version = item['metadata']['name'], item['metadata']['version']
                if name.lower() in SKIP:
                    continue
                versions[name] = version
                if item['download_info']['url'].startswith('file:'):
                    source = sources.setdefault(name, {**sdist(name, version), 'only-arches': []})
                else:
                    source = sources.setdefault(item['download_info']['url'], {
                        'type': 'file',
                        'url': item['download_info']['url'],
                        'sha256': item['download_info']['archive_info']['hashes']['sha256'],
                        'only-arches': [],
                    })
                source['only-arches'].append(arch)

    for source in sources.values():
        if len(source['only-arches']) == len(ARCHES):
            del source['only-arches']

    module = {
        'name': 'python-deps',
        'buildsystem': 'simple',
        'build-commands': [
            'pip3 install --no-index --no-build-isolation --find-links="file://${PWD}" --prefix="${FLATPAK_DEST}"'
            ' --no-deps *.whl *.tar.gz',
        ],
        'sources': sorted(sources.values(), key=lambda source: source['url'].rsplit('/', 1)[-1].lower()),
    }
    (HERE / 'python-deps.json').write_text(json.dumps(module, indent=2) + '\n')
    print('\n'.join(f'{name}=={version}' for name, version in sorted(versions.items(), key=lambda kv: kv[0].lower())))


if __name__ == '__main__':
    if not 2 <= len(sys.argv) <= 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
