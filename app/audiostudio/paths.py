"""Stable locations of the Tool's app/data/runtime folders. No side effects on import."""
from pathlib import Path
import os
import sys

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
DATA = ROOT / 'data'
RUNTIME = ROOT / 'runtime'

INPUTS = DATA / 'inputs'
MODELS = DATA / 'models'
JOBS = DATA / 'jobs'
SETTINGS = DATA / 'settings'
LOGS = DATA / 'logs'
REPORTS = DATA / 'reports'
WORKFLOWS = DATA / 'workflows'
PRESETS = DATA / 'presets'
SESSIONS = DATA / 'sessions'
PLUGIN_CACHE = DATA / 'settings' / 'plugins'

ENGINES = RUNTIME / 'engines'
DOWNLOADS = RUNTIME / 'downloads'
UPDATES = RUNTIME / 'updates'
BACKUPS = RUNTIME / 'backups'


def base_python():
    """Interpreter of the light application environment (runtime/python)."""
    if sys.platform == 'win32':
        candidates = (RUNTIME / 'python' / 'Scripts' / 'python.exe', RUNTIME / 'python' / 'python.exe')   # venv, or portable build
    else:
        candidates = (RUNTIME / 'python' / 'bin' / 'python',)
    return next((c for c in candidates if c.exists()), Path(sys.executable))


def engine_python(name):
    """Interpreter of a heavy engine environment (runtime/engines/<name>)."""
    root = ENGINES / name
    if sys.platform == 'win32':
        return root / 'Scripts' / 'python.exe'
    return root / 'bin' / 'python'


def ensure_data_layout():
    for folder in (INPUTS, MODELS, JOBS, SETTINGS, LOGS, REPORTS, WORKFLOWS, PRESETS, SESSIONS, PLUGIN_CACHE):
        folder.mkdir(parents=True, exist_ok=True)


def default_vst3_directories():
    """Standard VST3 locations for the current platform (only existing ones)."""
    candidates = []
    if sys.platform == 'win32':
        for env in ('CommonProgramFiles', 'CommonProgramW6432', 'CommonProgramFiles(x86)'):
            value = os.environ.get(env)
            if value:
                candidates.append(Path(value) / 'VST3')
        local = os.environ.get('LOCALAPPDATA')
        if local:
            candidates.append(Path(local) / 'Programs' / 'Common' / 'VST3')
    elif sys.platform == 'darwin':
        candidates += [Path('/Library/Audio/Plug-Ins/VST3'), Path.home() / 'Library/Audio/Plug-Ins/VST3']
    else:
        candidates += [Path('/usr/lib/vst3'), Path('/usr/local/lib/vst3'), Path.home() / '.vst3']
    seen, result = set(), []
    for path in candidates:
        key = str(path).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            result.append(path)
    return result
