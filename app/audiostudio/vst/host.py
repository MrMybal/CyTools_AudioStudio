"""VST3 hosting through pedalboard (JUCE).

Scanning and processing must happen in a worker process: a third-party plugin can
crash or hang, and the interface must survive that. This module is therefore plain
Python without ImGui; the workers in app/workers call it.

Plugin identity in workflows is the bundle path (``Something.vst3``). On Windows the
loadable file is ``<bundle>/Contents/x86_64-win/<name>.vst3``; both forms are accepted.
"""
import base64
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

CACHE_VERSION = 1
PLUGIN_KINDS = ('vst3', 'clap', 'lv2', 'jsfx')


def plugin_format(path):
    suffix = Path(path).suffix.lower().lstrip('.')
    return suffix if suffix in PLUGIN_KINDS else 'jsfx'



def loadable_path(path):
    """Resolve a bundle folder or a plain DLL to the file pedalboard can load."""
    path = Path(path)
    if path.is_file():
        return path
    if path.is_dir() and path.suffix.lower() in ('.lv2', '.clap'):
        return path
    if path.is_dir():
        if sys.platform == 'win32':
            arch = 'x86_64-win' if platform.machine().lower() in ('amd64', 'x86_64') else 'arm64-win'
            inner = path / 'Contents' / arch
            if inner.is_dir():
                candidates = sorted(p for p in inner.glob('*.vst3') if p.is_file())
                if candidates:
                    return candidates[0]
            candidates = sorted(p for p in path.rglob('*.vst3') if p.is_file())
            if candidates:
                return candidates[0]
        else:
            return path
    raise FileNotFoundError('VST3 plugin not found: ' + str(path))


def bundle_path(path):
    """Canonical bundle path (folder ending with .vst3, or the file itself)."""
    path = Path(path)
    for parent in [path] + list(path.parents):
        if parent.suffix.lower() in ('.vst3', '.clap', '.lv2') and parent.is_dir():
            return parent
    return path


def find_bundles(directories, max_depth=6):
    """Enumerate VST3 bundles below the given folders (no loading)."""
    found = []
    seen = set()
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        stack = [(directory, 0)]
        while stack:
            current, depth = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.suffix.lower() in ('.vst3', '.clap', '.lv2', '.jsfx') or (entry.is_file() and not entry.suffix and _is_jsfx(entry)):
                    key = str(entry.resolve()).casefold() if sys.platform == 'win32' else str(entry.resolve())
                    if key not in seen:
                        seen.add(key)
                        found.append(entry)
                elif entry.is_dir() and depth < max_depth and not entry.name.startswith('.'):
                    stack.append((entry, depth + 1))
    return sorted(found, key=lambda p: p.name.lower())


def _is_jsfx(path):
    try:
        with path.open('r', encoding='utf-8-sig', errors='replace') as f:
            head = f.read(16384)
        return 'desc:' in head and any(section in head for section in ('@sample', '@block', '@init'))
    except OSError:
        return False


def load(path, plugin_name=None):
    if plugin_format(path) != 'vst3':
        from ..plugins.native import NativePlugin
        return NativePlugin(path, plugin_name)
    from pedalboard import load_plugin
    file = loadable_path(path)
    if plugin_name:
        return load_plugin(str(file), plugin_name=plugin_name)
    return load_plugin(str(file))


def describe_parameter(name, parameter):
    info = {'id': name, 'label': getattr(parameter, 'label', name) or name, 'units': getattr(parameter, 'units', '') or ''}
    try:
        info['value'] = _plain(getattr(parameter, 'raw_value', None))
        info['rawValue'] = float(parameter.raw_value)
    except Exception:
        info['value'] = None
    value_range = getattr(parameter, 'range', None)
    if value_range:
        try:
            info['minimum'], info['maximum'] = float(value_range[0]), float(value_range[1])
            if len(value_range) > 2 and value_range[2] is not None:
                info['step'] = float(value_range[2])
        except (TypeError, ValueError):
            pass
    valid = getattr(parameter, 'valid_values', None)
    if valid and len(valid) <= 64:
        info['choices'] = [str(v) for v in valid]
    if hasattr(parameter, 'text'):
        info['displayValue'] = parameter.text
        info['normalized'] = True
    info['type'] = getattr(parameter, 'type', None).__name__ if getattr(parameter, 'type', None) else 'float'
    return info


def _plain(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def describe(path, plugin_name=None):
    """Load a plugin and report its identity and parameters (runs in a worker)."""
    started = time.monotonic()
    plugin = load(path, plugin_name)
    try:
        return _describe_loaded(path, plugin, started)
    finally:
        if hasattr(plugin, 'close'):
            plugin.close()


def _describe_loaded(path, plugin, started):
    parameters = {}
    for name in list(plugin.parameters):
        try:
            parameters[name] = describe_parameter(name, plugin.parameters[name])
        except Exception as exc:
            parameters[name] = {'id': name, 'error': str(exc)}
    return {'format': plugin_format(path).upper(), 'pluginId': getattr(plugin, 'metadata', {}).get('pluginId', ''), 'path': str(bundle_path(path)), 'file': str(loadable_path(path)), 'name': plugin.name,
            'manufacturer': plugin.manufacturer_name, 'version': plugin.version, 'category': getattr(plugin, 'category', ''),
            'isEffect': bool(plugin.is_effect), 'isInstrument': bool(plugin.is_instrument),
            'latencySamples': int(getattr(plugin, 'reported_latency_samples', 0) or 0),
            'parameters': parameters, 'loadSeconds': round(time.monotonic() - started, 3)}


def plugin_names(path):
    if plugin_format(path) != 'vst3':
        from ..plugins.native import probe
        return [row['name'] for row in probe(path)]
    from pedalboard import VST3Plugin
    return list(VST3Plugin.get_plugin_names_for_file(str(loadable_path(path))))


def apply_settings(plugin, params=None, state=None):
    """Restore a saved state first, then explicit parameter values on top."""
    if state:
        plugin.raw_state = base64.b64decode(state)
    for name, value in (params or {}).items():
        if name not in plugin.parameters:
            continue
        parameter = plugin.parameters[name]
        try:
            if isinstance(value, bool) or getattr(parameter, 'type', None) is bool:
                setattr(plugin, name, bool(value))
            elif isinstance(value, str) and getattr(parameter, 'valid_values', None) and value in parameter.valid_values:
                setattr(plugin, name, value)
            else:
                setattr(plugin, name, float(value))
        except Exception:
            # Fall back to the normalised raw value when a typed set is refused.
            try:
                parameter.raw_value = float(value)
            except Exception:
                pass


def capture(plugin):
    """Serialisable snapshot of a plugin: explicit parameters plus opaque state."""
    if hasattr(plugin, 'refresh'):
        plugin.refresh()
    params = {}
    for name in list(plugin.parameters):
        try:
            params[name] = _plain(getattr(plugin, name))
        except Exception:
            pass
    return {'params': params, 'state': base64.b64encode(bytes(plugin.raw_state)).decode('ascii')}


def process(plugin, audio, samplerate, reset=True):
    output = plugin(np.ascontiguousarray(audio, dtype=np.float32), float(samplerate), reset=reset)
    return np.ascontiguousarray(np.asarray(output, dtype=np.float32))


def cache_key(path):
    file = loadable_path(path)
    files = sorted(p for p in file.rglob('*') if p.is_file()) if file.is_dir() else [file]
    # JSFX includes live beside the script; changing one invalidates the description.
    if plugin_format(path) == 'jsfx':
        files = sorted(p for p in file.parent.rglob('*') if p.is_file() and p.suffix.lower() in ('', '.jsfx', '.jsfx-inc'))
    digest = hashlib.sha256(f'{file.resolve()}|formats-v2'.encode())
    for item in files:
        stat = item.stat()
        digest.update(f'{item}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8'))
    return digest.hexdigest()


def read_cache(cache_dir):
    path = Path(cache_dir) / 'vst3-catalogue.json'
    try:
        value = json.loads(path.read_text('utf-8-sig'))
        return value if isinstance(value, dict) and value.get('version') == CACHE_VERSION else {'version': CACHE_VERSION, 'plugins': {}}
    except (OSError, ValueError):
        return {'version': CACHE_VERSION, 'plugins': {}}


def write_cache(cache_dir, value):
    path = Path(cache_dir) / 'vst3-catalogue.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), 'utf-8')
    temp.replace(path)
    return path
