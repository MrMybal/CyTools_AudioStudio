"""Voice presets: the exact generation settings of a voice, saved to regenerate it later.

A preset stores the backend, the model, every parameter except the spoken text, the
reference audio (path and SHA-256 so a changed file is detected), an optional
post-processing workflow name and notes. Saved in data/presets/voices/<id>.json.
Loading a preset never starts a generation.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from ..paths import PRESETS

FORMAT = 'cytools-audiostudio-voice-preset'
SCHEMA_VERSION = 1
FOLDER = PRESETS / 'voices'
OPERATIONS = {'piper': 'voice_piper', 'qwen3tts': 'voice_qwen3tts', 'fishspeech': 'voice_fishspeech'}
TEXT_FIELDS = ('text', 'turns')


class PresetError(ValueError):
    pass


def slug(name):
    value = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')
    return value[:60] or 'voice'


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def build(name, backend, parameters, *, model_id='', post_workflow='', notes='', preset_id=''):
    if backend not in OPERATIONS:
        raise PresetError('Unknown voice backend: ' + str(backend))
    params = {k: v for k, v in dict(parameters or {}).items() if k not in TEXT_FIELDS and k != 'post_workflow'}
    references = []
    for key in ('reference_audio',):
        path = params.get(key)
        if path and Path(path).is_file():
            references.append({'field': key, 'path': str(Path(path).resolve()), 'sha256': _sha256(path), 'size': Path(path).stat().st_size})
    for index, item in enumerate(params.get('references') or []):
        path = item.get('audio') if isinstance(item, dict) else None
        if path and Path(path).is_file():
            references.append({'field': f'references[{index}].audio', 'path': str(Path(path).resolve()), 'sha256': _sha256(path), 'size': Path(path).stat().st_size})
    return {'format': FORMAT, 'schemaVersion': SCHEMA_VERSION, 'id': preset_id or slug(name) + '-' + uuid.uuid4().hex[:6], 'name': str(name)[:120],
            'backend': backend, 'operationId': OPERATIONS[backend], 'modelId': model_id or params.get('model', ''), 'parameters': params,
            'references': references, 'postWorkflow': post_workflow or '', 'notes': str(notes or '')[:2000],
            'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S'), 'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%S')}


def validate(value):
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        raise PresetError('Not an AudioStudio voice preset')
    if value.get('schemaVersion') != SCHEMA_VERSION:
        raise PresetError('Unsupported preset version')
    if value.get('backend') not in OPERATIONS:
        raise PresetError('Unknown voice backend in preset')
    if not isinstance(value.get('parameters'), dict):
        raise PresetError('Preset parameters must be an object')
    value['operationId'] = OPERATIONS[value['backend']]
    return value


def path_for(preset_id):
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(preset_id))
    return FOLDER / (safe + '.json')


def _store_references(preset):
    """Copy reference recordings next to the preset so it stays valid when the originals move."""
    import shutil
    refs = FOLDER / 'refs'
    for index, item in enumerate(preset.get('references', [])):
        source = Path(item['path'])
        if not source.is_file() or source.resolve().is_relative_to(refs.resolve()):
            continue
        refs.mkdir(parents=True, exist_ok=True)
        target = refs / f"{preset['id']}-{index}{source.suffix.lower()}"
        shutil.copy2(source, target)
        field = item['field']
        if field == 'reference_audio':
            preset['parameters']['reference_audio'] = str(target)
        elif field.startswith('references['):
            position = int(field[len('references['):field.index(']')])
            preset['parameters']['references'][position]['audio'] = str(target)
        item['original'] = str(source)
        item['path'] = str(target)
    return preset


def save(preset):
    preset = validate(preset)
    preset = _store_references(preset)
    preset['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    FOLDER.mkdir(parents=True, exist_ok=True)
    target = path_for(preset['id'])
    temp = target.with_suffix('.tmp' + uuid.uuid4().hex[:6])
    temp.write_text(json.dumps(preset, indent=2, ensure_ascii=False), 'utf-8')
    temp.replace(target)
    return target


def load(preset_id):
    target = path_for(preset_id)
    if not target.is_file():
        candidate = Path(preset_id)
        if candidate.is_file():
            target = candidate
        else:
            raise PresetError('Unknown voice preset: ' + str(preset_id))
    return validate(json.loads(target.read_text('utf-8-sig')))


def delete(preset_id):
    target = path_for(preset_id)
    if not target.is_file():
        raise PresetError('Unknown voice preset: ' + str(preset_id))
    target.unlink()
    for ref in (FOLDER / 'refs').glob(f'{preset_id}-*'):
        ref.unlink()
    return True


def list_all():
    items = []
    if FOLDER.is_dir():
        for path in sorted(FOLDER.glob('*.json')):
            try:
                value = validate(json.loads(path.read_text('utf-8-sig')))
                items.append({'id': value['id'], 'name': value['name'], 'backend': value['backend'], 'modelId': value.get('modelId', ''),
                              'postWorkflow': value.get('postWorkflow', ''), 'references': len(value.get('references', [])),
                              'updatedAt': value.get('updatedAt', ''), 'notes': value.get('notes', ''), 'path': str(path)})
            except (PresetError, ValueError, OSError) as exc:
                items.append({'id': path.stem, 'name': path.stem, 'backend': '', 'error': str(exc), 'path': str(path)})
    return items


def check_references(preset):
    """Warn when a reference recording changed since the preset was saved."""
    warnings = []
    for item in preset.get('references', []):
        path = Path(item['path'])
        if not path.is_file():
            warnings.append(f"Reference {item['field']} is missing: {path}")
        elif path.stat().st_size != item.get('size') or _sha256(path) != item.get('sha256'):
            warnings.append(f"Reference {item['field']} changed since the preset was saved: {path}")
    return warnings


def parameters_for(preset, text=None, turns=None, overrides=None):
    """Operation parameters = preset parameters + the text to speak + explicit overrides."""
    params = dict(preset['parameters'])
    if preset['backend'] == 'fishspeech':
        if turns is None:
            if text is None:
                raise PresetError('Fish Speech presets need text or turns')
            turns = [{'speaker': 0, 'text': text, 'expression': params.pop('expression', '') if isinstance(params.get('expression'), str) else ''}]
        params['turns'] = turns
    else:
        if text is None:
            raise PresetError('Text to speak is required')
        params['text'] = text
    params.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return params
