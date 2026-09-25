"""Build the release assets of CyTools_AudioStudio.

    runtime/python/Scripts/python.exe app/scripts/build_release.py [--skip-portable] [--python-nupkg PATH]

Writes runtime/build/release/v<version>/:
  cytools-app.zip (+ .sha256)          the application stream read by the Updates tab: app/ only,
                                       without bytecode, tests included; entries start with app/
  CyTools_AudioStudio-<version>-win64.zip (+ .sha256)
                                       portable Windows build: launcher, app/, docs, LICENSE and a private
                                       Python 3.11 (official NuGet build) with the base requirements and the
                                       pinned CyToolsCore SDK already installed. Engines and models are still
                                       installed by the application (Models tab / setup_engine.py).
  CyTools_AudioStudio.exe (+ .sha256)  the launcher alone
  SHA256SUMS.txt

The portable Python is built in a temporary folder from the NuGet package (downloaded when no
--python-nupkg is given) and is never the developer's own runtime/python venv.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
PYTHON_NUGET_VERSION = '3.11.9'
PYTHON_NUGET_URL = 'https://www.nuget.org/api/v2/package/python/' + PYTHON_NUGET_VERSION
SDK_REQUIREMENT = 'cytools-core[mcp] @ git+https://github.com/MrMybal/CyToolsCore.git@442f537'
EXCLUDED_DIRS = {'__pycache__', '.pytest_cache'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.obj'}


def say(message):
    print('[release] ' + message, flush=True)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_sum(path):
    digest = sha256_of(path)
    Path(str(path) + '.sha256').write_text(f'{digest}  {Path(path).name}\n', 'utf-8')
    return digest


def app_files():
    for path in sorted(APP.rglob('*')):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(APP).parts) or path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield path


def build_app_zip(target):
    say('application stream: ' + target.name)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in app_files():
            bundle.write(path, 'app/' + path.relative_to(APP).as_posix())
    return target


def obtain_nupkg(folder, given=None):
    if given:
        return Path(given)
    target = folder / f'python.{PYTHON_NUGET_VERSION}.nupkg'
    if not target.exists():
        say(f'downloading the official Python {PYTHON_NUGET_VERSION} NuGet build from nuget.org')
        request = urllib.request.Request(PYTHON_NUGET_URL, headers={'User-Agent': 'CyTools-AudioStudio-release'})
        with urllib.request.urlopen(request, timeout=120) as response, open(target, 'wb') as handle:
            shutil.copyfileobj(response, handle)
    return target


def build_portable_python(destination, nupkg):
    """Extract tools/ of the NuGet package into destination and install the base requirements."""
    say('portable Python -> ' + str(destination))
    with zipfile.ZipFile(nupkg) as bundle:
        for info in bundle.infolist():
            if not info.filename.startswith('tools/') or info.is_dir():
                continue
            relative = Path(info.filename[len('tools/'):])
            if '..' in relative.parts:
                raise ValueError('unsafe entry in the NuGet package: ' + info.filename)
            out = destination / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, open(out, 'wb') as handle:
                shutil.copyfileobj(source, handle)
    python = destination / 'python.exe'
    if not python.exists():
        raise RuntimeError('python.exe missing after extracting the NuGet package')
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK='1', PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([str(python), '-m', 'ensurepip', '--upgrade'], check=True, env=env)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-warn-script-location', '--upgrade', 'pip'], check=True, env=env)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-warn-script-location', SDK_REQUIREMENT], check=True, env=env)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-warn-script-location', '--keyring-provider', 'disabled', '-r', str(APP / 'requirements.txt')], check=True, env=env)
    # bytecode written during pip's own run is dead weight
    for cache in destination.rglob('__pycache__'):
        shutil.rmtree(cache, ignore_errors=True)
    check = subprocess.run([str(python), '-c', 'import cytools_core, imgui_bundle, pedalboard, sounddevice, soundfile, scipy, av, pyloudnorm, matchering; print("ok")'],
                           capture_output=True, text=True, env=env)
    if check.returncode != 0 or 'ok' not in check.stdout:
        raise RuntimeError('portable Python import check failed:\n' + check.stdout + check.stderr)
    return python


def build_portable_zip(target, version, nupkg):
    say('portable build: ' + target.name)
    with tempfile.TemporaryDirectory(prefix='audiostudio-release-') as temp:
        stage = Path(temp) / 'CyTools_AudioStudio'
        (stage / 'app').mkdir(parents=True)
        for path in app_files():
            out = stage / 'app' / path.relative_to(APP)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
        for name in ('CyTools_AudioStudio.exe', 'CyTools_AudioStudio.sh', 'README.md', 'LISEZ-MOI.md', 'LICENSE'):
            source = ROOT / name
            if not source.exists():
                raise RuntimeError('missing at the Tool root: ' + name)
            shutil.copy2(source, stage / name)
        (stage / 'data').mkdir()
        shutil.copy2(ROOT / 'data' / 'README.md', stage / 'data' / 'README.md')
        (stage / 'runtime').mkdir()
        build_portable_python(stage / 'runtime' / 'python', nupkg)
        (stage / 'PORTABLE.txt').write_text(
            f'CyTools_AudioStudio {version} - portable Windows x64 build\n\n'
            'Unzip anywhere (a path without accents is safest) and double-click CyTools_AudioStudio.exe.\n'
            'runtime/python is a private Python 3.11 with the interface, the CLI, MCP, the effects and VST3 hosting.\n'
            'Generation models need the engines: install them from the Models tab (or app/setup_engine.py); Git must be on the PATH for that.\n'
            'Model weights are downloaded by the application into data/models.\n', 'utf-8')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    bundle.write(path, path.relative_to(stage.parent).as_posix())
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-portable', action='store_true', help='only the application stream and the launcher')
    parser.add_argument('--python-nupkg', help='local python.<version>.nupkg instead of downloading it')
    parser.add_argument('--output', help='output folder (default runtime/build/release/v<version>)')
    args = parser.parse_args()
    version = json.loads((APP / 'release.json').read_text('utf-8-sig'))['version']
    output = Path(args.output) if args.output else ROOT / 'runtime' / 'build' / 'release' / ('v' + version)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    started = time.monotonic()
    assets = []
    assets.append(build_app_zip(output / 'cytools-app.zip'))
    launcher = ROOT / 'CyTools_AudioStudio.exe'
    if not launcher.exists():
        raise RuntimeError('CyTools_AudioStudio.exe is missing: run app/build_launcher.ps1 first')
    shutil.copy2(launcher, output / launcher.name)
    assets.append(output / launcher.name)
    if not args.skip_portable:
        nupkg = obtain_nupkg(ROOT / 'runtime' / 'downloads', args.python_nupkg)
        assets.append(build_portable_zip(output / f'CyTools_AudioStudio-{version}-win64.zip', version, nupkg))
    sums = []
    for asset in assets:
        digest = write_sum(asset)
        sums.append(f'{digest}  {asset.name}')
        say(f'{asset.name}: {asset.stat().st_size / 1e6:.1f} MB  sha256 {digest[:16]}...')
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', 'utf-8')
    say(f'done in {time.monotonic() - started:.0f} s -> {output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
