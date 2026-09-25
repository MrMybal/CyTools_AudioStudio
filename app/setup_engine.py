"""Create or repair an engine environment declared in app/engines.json.

    python app/setup_engine.py torch [--cpu-only] [--sources-only] [--status] [--no-sources]
    python app/setup_engine.py piper
    python app/setup_engine.py --status-all

Environments are created at their final path (runtime/engines/<name>) with the base
interpreter of the private runtime; a venv is never moved. PyTorch is installed first
from the wheel index declared for the engine, pinned by a constraints file so that a
later dependency cannot swap the CUDA build for a CPU wheel. Vendored sources are git
checkouts at pinned revisions. The last step is an import check inside the new
environment; nothing is reported installed before that check passes.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parent
ROOT = APP.parent
RUNTIME = ROOT / 'runtime'
SPEC = json.loads((APP / 'engines.json').read_text('utf-8-sig'))


def log(message):
    print('[setup_engine] ' + message, flush=True)


def base_interpreter():
    # A venv shim cannot reliably create another venv: use the real interpreter.
    return getattr(sys, '_base_executable', None) or sys.executable


def engine_root(name):
    return ROOT / SPEC['engines'][name]['directory']


def engine_python(name):
    root = engine_root(name)
    return root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def sources_root():
    return RUNTIME / 'sources'


def run(command, **kwargs):
    log(' '.join(str(c) for c in command))
    subprocess.run([str(c) for c in command], check=True, **kwargs)


def pip(python, *args, env=None):
    run([python, '-m', 'pip', *args], env=env)


def install_sources(name):
    spec = SPEC['engines'][name]
    result = {}
    for source, item in spec.get('sources', {}).items():
        target = sources_root() / source
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target / '.git').is_dir():
            if target.exists() and any(target.iterdir()):
                raise SystemExit(f'{target} exists and is not a git checkout; remove it or fix it manually')
            run(['git', 'clone', '--no-checkout', '--filter=blob:none', item['repository'], str(target)])
        head = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True)
        required = target / item['requiredFile']
        populated = required.is_file()
        if head.stdout.strip() != item['revision'] or not populated:
            if populated:
                dirty = subprocess.run(['git', '-C', str(target), 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
                if dirty:
                    raise SystemExit(f'{target} has local changes; refusing to move it to {item["revision"]}')
            if subprocess.run(['git', '-C', str(target), 'cat-file', '-e', item['revision'] + '^{commit}'], capture_output=True).returncode != 0:
                run(['git', '-C', str(target), 'fetch', '--depth', '1', 'origin', item['revision']])
            # --detach also populates the work tree of a --no-checkout clone.
            run(['git', '-C', str(target), 'checkout', '--detach', item['revision']])
        if not required.is_file():
            raise SystemExit(f'Required file missing after checkout: {required}')
        result[source] = {'path': str(target), 'revision': item['revision']}
        log(f'source {source} ready at {item["revision"][:12]}')
    return result


def install_environment(name, cpu_only=False):
    spec = SPEC['engines'][name]
    root = engine_root(name)
    python = engine_python(name)
    if not python.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        run([base_interpreter(), '-m', 'venv', str(root)])
    pip(python, 'install', '--upgrade', 'pip', 'wheel')
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_KEYRING_PROVIDER='disabled')
    torch_spec = spec.get('torch')
    constraints = []
    if torch_spec:
        block = torch_spec['cpu'] if cpu_only else torch_spec
        pip(python, 'install', '--index-url', block['index'], *block['packages'], env=env)
        constraints = [p.split('+')[0] for p in block['packages']]
        (root / 'cytools-constraints.txt').write_text('\n'.join(constraints) + '\n', 'utf-8')
    requirements = APP / spec['requirements']
    args = ['install', '-r', str(requirements)]
    if constraints:
        args += ['-c', str(root / 'cytools-constraints.txt')]
    pip(python, *args, env=env)
    return python


def verify(name, cpu_only=False):
    spec = SPEC['engines'][name]
    python = engine_python(name)
    modules = spec.get('verify', [])
    script = (
        'import importlib, json, sys\n'
        'report = {"python": sys.version.split()[0], "modules": {}}\n'
        f'for name in {modules!r}:\n'
        '    try:\n'
        '        module = importlib.import_module(name)\n'
        '        report["modules"][name] = getattr(module, "__version__", "ok")\n'
        '    except Exception as exc:\n'
        '        report["modules"][name] = "ERROR: " + str(exc)\n'
        'try:\n'
        '    import torch\n'
        '    report["torch"] = torch.__version__\n'
        '    report["cuda"] = torch.cuda.is_available()\n'
        '    report["device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"\n'
        'except Exception:\n'
        '    pass\n'
        'print(json.dumps(report))\n'
    )
    env = dict(os.environ)
    for source in spec.get('sources', {}):
        env['PYTHONPATH'] = str(sources_root() / source) + os.pathsep + env.get('PYTHONPATH', '')
    output = subprocess.run([str(python), '-c', script], capture_output=True, text=True, env=env, cwd=str(ROOT))
    if output.returncode != 0:
        raise SystemExit('Verification process failed:\n' + output.stderr[-4000:])
    report = json.loads(output.stdout.strip().splitlines()[-1])
    failed = {k: v for k, v in report['modules'].items() if str(v).startswith('ERROR')}
    if failed:
        raise SystemExit('Missing modules in ' + name + ': ' + json.dumps(failed, indent=2))
    if spec.get('torch') and not cpu_only and not report.get('cuda'):
        raise SystemExit('CUDA is not available in the new environment (torch ' + str(report.get('torch')) + ')')
    return report


def status(name):
    spec = SPEC['engines'][name]
    python = engine_python(name)
    info = {'engine': name, 'label': spec['label'], 'python': str(python), 'installed': False, 'sources': {}, 'report': None}
    for source, item in spec.get('sources', {}).items():
        target = sources_root() / source
        head = ''
        if (target / '.git').is_dir():
            head = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        info['sources'][source] = {'present': (target / item['requiredFile']).is_file(), 'revision': head, 'expected': item['revision']}
    receipt = engine_root(name) / 'cytools-engine.json'
    if python.exists() and receipt.is_file():
        try:
            info['report'] = json.loads(receipt.read_text('utf-8'))
            info['installed'] = all(v['present'] and v['revision'] == v['expected'] for v in info['sources'].values())
        except ValueError:
            info['report'] = None
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('engine', nargs='?', choices=list(SPEC['engines']))
    parser.add_argument('--cpu-only', action='store_true')
    parser.add_argument('--sources-only', action='store_true')
    parser.add_argument('--no-sources', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--status-all', action='store_true')
    args = parser.parse_args()
    if args.status_all:
        print(json.dumps({name: status(name) for name in SPEC['engines']}, indent=2))
        return 0
    if not args.engine:
        parser.error('engine name required')
    if args.status:
        print(json.dumps(status(args.engine), indent=2))
        return 0
    if not args.no_sources:
        install_sources(args.engine)
    if args.sources_only:
        return 0
    install_environment(args.engine, cpu_only=args.cpu_only)
    report = verify(args.engine, cpu_only=args.cpu_only)
    report['cpuOnly'] = bool(args.cpu_only)
    receipt = engine_root(args.engine) / 'cytools-engine.json'
    receipt.write_text(json.dumps(report, indent=2), 'utf-8')
    log('engine ' + args.engine + ' ready: ' + json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
