"""Read app/engines.json and report the state of each engine environment.

Nothing here installs anything: installation is app/setup_engine.py, driven by the
``install_engine`` operation or the command line. No torch import ever happens in
the application process.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from ..paths import APP, ROOT, RUNTIME

SPEC_PATH = APP / 'engines.json'


def spec():
    return json.loads(SPEC_PATH.read_text('utf-8-sig'))


def engine_names():
    return list(spec()['engines'])


def engine_for_backend(backend_id):
    for name, item in spec()['engines'].items():
        if backend_id in item.get('backends', []):
            return name
    return None


def engine_root(name):
    return ROOT / spec()['engines'][name]['directory']


def engine_python(name):
    root = engine_root(name)
    return root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def source_path(source_name):
    return RUNTIME / 'sources' / source_name


def receipt(name):
    path = engine_root(name) / 'cytools-engine.json'
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return None


def sources_status(name):
    result = {}
    for source, item in spec()['engines'][name].get('sources', {}).items():
        target = source_path(source)
        head = ''
        if (target / '.git').is_dir():
            head = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
        result[source] = {'present': (target / item['requiredFile']).is_file(), 'revision': head,
                          'expected': item['revision'], 'ok': (target / item['requiredFile']).is_file() and head == item['revision']}
    return result


def status(name):
    item = spec()['engines'][name]
    python = engine_python(name)
    report = receipt(name)
    sources = sources_status(name)
    installed = python.exists() and report is not None and all(s['ok'] for s in sources.values())
    state = 'Installed' if installed else 'Partial' if python.exists() else 'NotInstalled'
    return {'engine': name, 'label': item['label'], 'state': state, 'installed': installed, 'python': str(python),
            'pythonExists': python.exists(), 'report': report, 'sources': sources, 'backends': item.get('backends', []),
            'estimatedBytes': item.get('estimatedBytes', 0), 'cuda': bool(report and report.get('cuda')),
            'device': (report or {}).get('device', ''), 'torch': (report or {}).get('torch', '')}


def status_all():
    return {name: status(name) for name in engine_names()}


def base_environment():
    """Environment for workers of the light base interpreter (DSP, procedural SFX)."""
    env = dict(os.environ)
    env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'})
    env['PYTHONPATH'] = str(APP) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def worker_environment(name):
    """Environment variables for a worker process of this engine: offline, sources on path."""
    env = dict(os.environ)
    env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'DIFFUSERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'TOKENIZERS_PARALLELISM': 'false',
                'HF_HOME': str(RUNTIME / 'huggingface')})
    paths = [str(source_path(source)) for source in spec()['engines'][name].get('sources', {})]
    paths.append(str(APP))
    env['PYTHONPATH'] = os.pathsep.join(paths + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    return env


def require(name):
    """Raise a CyToolError when the engine is not usable."""
    from cytools_core import CyToolError
    info = status(name)
    if not info['installed']:
        raise CyToolError('MissingDependency', f'Engine "{name}" is not installed. Open Installation > Engines or run: python app/setup_engine.py {name}',
                          recoverable=True, details={'engine': name, 'state': info['state']})
    return info
