"""Workflow document: versioned JSON, validated, without executing anything on load.

{
  "format": "cytools-audiostudio-workflow", "schemaVersion": 1,
  "name": "Voice polish", "description": "", "createdAt": "...", "updatedAt": "...",
  "tail": {"enabled": true, "threshold_db": -60, "max_seconds": 10, "hold_seconds": 0.1},
  "nodes": [
    {"id": "n1", "kind": "effect", "effect": "highpass", "params": {"cutoff_hz": 80}, "enabled": true, "mix": 1.0, "label": ""},
    {"id": "n2", "kind": "vst3", "plugin": "C:/.../Plugin.vst3", "pluginName": "...", "params": {"gain": 0.5}, "state": "<base64>", "enabled": true, "mix": 1.0},
    {"id": "n3", "kind": "model", "model": "denoise.deepfilternet", "params": {}, "enabled": true, "mix": 1.0}
  ]
}
"""
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import re
import uuid

FORMAT = 'cytools-audiostudio-workflow'
SCHEMA_VERSION = 1
NODE_KINDS = ('effect', 'vst3', 'model')
MAX_NODES = 64


class WorkflowError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def new_workflow(name='Untitled workflow', nodes=None, tail=None, description=''):
    return {'format': FORMAT, 'schemaVersion': SCHEMA_VERSION, 'name': name, 'description': description,
            'createdAt': _now(), 'updatedAt': _now(), 'tail': normalize_tail(tail), 'nodes': [normalize_node(n) for n in (nodes or [])]}


def normalize_tail(value):
    from ..dsp.tail import TailSettings
    return TailSettings.from_dict(value).as_dict()


def new_node(kind, **fields):
    node = {'id': uuid.uuid4().hex[:8], 'kind': kind, 'enabled': True, 'mix': 1.0, 'label': '', 'params': {}}
    node.update(fields)
    return normalize_node(node)


def normalize_node(node):
    if not isinstance(node, dict):
        raise WorkflowError('Node must be an object')
    kind = node.get('kind')
    if kind not in NODE_KINDS:
        raise WorkflowError('Unknown node kind: ' + str(kind))
    result = {'id': str(node.get('id') or uuid.uuid4().hex[:8]), 'kind': kind,
              'enabled': bool(node.get('enabled', True)), 'label': str(node.get('label', '') or ''),
              'params': dict(node.get('params') or {})}
    try:
        result['mix'] = max(0.0, min(1.0, float(node.get('mix', 1.0))))
    except (TypeError, ValueError):
        raise WorkflowError('Node mix must be a number between 0 and 1')
    if kind == 'effect':
        from ..dsp import effects
        effect_id = str(node.get('effect', ''))
        spec = effects.REGISTRY.get(effect_id)
        if spec is None:
            raise WorkflowError('Unknown effect: ' + effect_id)
        result['effect'] = effect_id
        result['params'] = spec.normalize(result['params'])
    elif kind == 'vst3':
        plugin = str(node.get('plugin', '') or '')
        if not plugin:
            raise WorkflowError('VST3 node requires a plugin path')
        result['plugin'] = plugin
        result['pluginName'] = str(node.get('pluginName', '') or '')
        result['params'] = {str(k): v for k, v in result['params'].items() if isinstance(v, (int, float, str, bool))}
        state = node.get('state', '')
        if state and not isinstance(state, str):
            raise WorkflowError('VST3 state must be a base64 string')
        result['state'] = state or ''
    elif kind == 'model':
        model = str(node.get('model', '') or '')
        if not re.match(r'^[a-z0-9_.-]+$', model):
            raise WorkflowError('Model node requires a model id')
        result['model'] = model
    return result


def validate(document):
    if not isinstance(document, dict):
        raise WorkflowError('Workflow must be a JSON object')
    if document.get('format') != FORMAT:
        raise WorkflowError('Not an AudioStudio workflow')
    if document.get('schemaVersion') != SCHEMA_VERSION:
        raise WorkflowError('Unsupported workflow schema version: ' + str(document.get('schemaVersion')))
    nodes = document.get('nodes')
    if not isinstance(nodes, list):
        raise WorkflowError('Workflow nodes must be a list')
    if len(nodes) > MAX_NODES:
        raise WorkflowError(f'Workflow has more than {MAX_NODES} nodes')
    result = copy.deepcopy(document)
    result['name'] = str(document.get('name') or 'Untitled workflow')[:200]
    result['description'] = str(document.get('description') or '')[:2000]
    result['tail'] = normalize_tail(document.get('tail'))
    result['nodes'] = [normalize_node(n) for n in nodes]
    ids = [n['id'] for n in result['nodes']]
    if len(set(ids)) != len(ids):
        raise WorkflowError('Duplicate node ids')
    result.setdefault('createdAt', _now())
    result['updatedAt'] = document.get('updatedAt') or _now()
    return result


def loads(text):
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise WorkflowError('Invalid JSON: ' + str(exc)) from exc
    return validate(value)


def load(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise WorkflowError('Workflow file is larger than 8 MiB')
    return loads(path.read_text('utf-8-sig'))


def dumps(document):
    return json.dumps(validate(document), indent=2, ensure_ascii=False, allow_nan=False) + '\n'


def save(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = validate(document)
    document['updatedAt'] = _now()
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)
    return path


def safe_name(name):
    cleaned = re.sub(r'[^A-Za-z0-9._ -]+', '_', str(name)).strip(' ._')
    return cleaned[:80] or 'workflow'


def list_workflows(folder):
    folder = Path(folder)
    entries = []
    if not folder.is_dir():
        return entries
    for path in sorted(folder.glob('*.json')):
        try:
            document = load(path)
            entries.append({'path': str(path), 'name': document['name'], 'nodes': len(document['nodes']),
                            'updatedAt': document.get('updatedAt', ''), 'description': document.get('description', '')})
        except (WorkflowError, OSError, ValueError) as exc:
            entries.append({'path': str(path), 'name': path.stem, 'nodes': 0, 'error': str(exc)})
    return entries


def summary(document):
    parts = []
    for node in document.get('nodes', []):
        if not node.get('enabled', True):
            continue
        if node['kind'] == 'effect':
            parts.append(node['effect'])
        elif node['kind'] == 'vst3':
            parts.append('vst3:' + (node.get('pluginName') or Path(node['plugin']).stem))
        else:
            parts.append('model:' + node['model'])
    return ' > '.join(parts) if parts else '(empty)'
